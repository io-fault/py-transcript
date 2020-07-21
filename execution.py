"""
# System process status display using transaction frames.
"""
import os
import collections
import typing
import signal
from dataclasses import dataclass

from ..context import tools
from ..time.sysclock import elapsed as time
from ..system import execution
from ..status.frames import stdio
from ..status.types import Report

from . import io
from .frames import protocol as metrics_protocol

@dataclass
class Traps:
	"""
	# Callback set for &dispatch.

	# [ Properties ]
	# /eox/
		# End of transaction callback.
		# Called whenever a transaction is closed by a job.
	# /eop/
		# End of process callback.
		# Called whenever a process of a job exits.
	# /eog/
		# End of group callback.
	"""

	@staticmethod
	def nop(*args):
		pass

	@classmethod
	def construct(Class, eox=nop, eop=nop, eog=nop):
		return Class(eox, eop, eog)

	eox: typing.Callable[[], None] = None
	eop: typing.Callable[[], None] = None
	eog: typing.Callable[[], None] = None

def transaction(synopsis, duration):
	"""
	# Create aggregate status frame for the transaction.
	"""
	from ..status import frames
	from ..status import types

	msg = types.Message.from_string_v1("transaction[><]: Execution", protocol=frames.protocol)
	msg.msg_parameters['envelope-fields'] = [synopsis]
	msg.msg_parameters['data'] = types.Parameters.from_pairs_v1([
		('duration', duration),
	])

	return msg

def _launch(status, stderr=2, stdin=0):
	try:
		category, dimensions, xqual, xcontext, ki = next(status['process-queue'])
		status['channel'] = xqual
	except StopIteration:
		return None

	rfd, wfd = os.pipe()
	try:
		status['pid'] = ki.spawn(fdmap=[(0,0), (wfd,1), (2,2)])
		os.close(wfd)
	except:
		os.close(rfd)
		os.close(wfd)
		raise

	return (rfd, category, dimensions)

def dispatch(traps, plan, control, monitors, summary, title, queue, window=8, range=range, next=next):
	"""
	# Execute a sequence of system commands while displaying their status
	# according to the transaction messages they emit to standard out.

	# Commands are executed simultaneously so long as a monitor is available to display
	# their status.
	"""

	unpack, pack = stdio()
	total_messages = 0
	message_count = 0
	nmonitors = len(monitors)
	ioa = io.FrameArray(unpack)

	stctl = control
	available = collections.deque(range(nmonitors))
	statusd = {}
	processing = True
	last = time()
	summary.title(title, '*')
	mtotals = summary.metrics
	mtotals.clear()

	try:
		ioa.__enter__()
		while processing:
			if available:
				# Open processing lanes take from queue.
				for ident in queue.take(len(available)):
					lid = available.popleft()
					kii = iter(plan(ident))

					status = statusd[lid] = {
						'channel': None,
						'source': ident,
						'process-queue': kii,
						'transactions': collections.defaultdict(list),
					}

					monitor = monitors[lid]
					monitor.metrics.clear()

					next_channel = _launch(status)
					if next_channel is None:
						queue.finish(status['source'])
						stctl.erase(monitor)
						available.append(lid)
						continue

					monitor.title(next_channel[1], *next_channel[2])
					ioa.connect(lid, next_channel[0])
					stctl.install(monitor)

				stctl.flush()
				if queue.terminal():
					if not statusd:
						# Queue has nothing and statusd is empty? EOF.
						processing = False
						continue
					elif available:
						# End of queue and still running.
						# Check existing jobs for further work.
						sources = list(statusd)
						for lid in sources:
							while available:
								status = dict(statusd[lid])
								next_channel = _launch(status)
								if next_channel is None:
									# continues for-loop
									break
								else:
									xlid = available.popleft()
									status['transactions'] = collections.defaultdict(list)
									statusd[xlid] = status
									monitor = monitors[xlid]

									monitor.title(next_channel[1], *next_channel[2])
									ioa.connect(xlid, next_channel[0])
									stctl.install(monitor)
							else:
								# No more availability, break out of for-loop.
								break

			# Cycle through sources, flush when complete.
			for lid, sframes in ioa:
				status = statusd[lid]
				xacts = status['transactions']
				srcid = status['source']
				monitor = monitors[lid]
				metrics = monitor.metrics

				if sframes is None:
					# Closed.
					pid = status['pid']
					exit_status = execution.reap(pid, options=0)

					# Send final snapshot to output. (stdout)
					traps.eop(pack, monitor, status['channel'], pid, exit_status)

					next_channel = _launch(status)
					monitor.metrics.clear()

					if next_channel is not None:
						ioa.connect(lid, next_channel[0])
						monitor.title(next_channel[1], *next_channel[2])
						stctl.install(monitor)
						continue

					queue.finish(status['source'])
					del statusd[lid]
					available.append(lid)

					summary.title(title, '/'.join(map(str, queue.status())))
					stctl.install(summary)
					status.clear()
					continue

				nframes = len(sframes)
				message_count += nframes

				for channel, msg in sframes:
					evtype = msg.msg_event.symbol
					xacts[channel].append(msg)

					data = msg.msg_parameters['data']
					if isinstance(data, Report) and data.event.protocol == metrics_protocol:
						# Metrics update.
						metrics.update('duration', data.r_parameters['time'], 1)
						mtotals.update('duration', data.r_parameters['time'], 1)

						fnames = data.r_parameters['fields']
						funits = data.r_parameters['units']
						fcounts = data.r_parameters['counts']
						for n, u, c in zip(fnames, funits, fcounts):
							metrics.update(n, u, c)
							mtotals.update(n, u, c)

					if evtype == 'transaction-stopped':
						metrics.update('executing', -1, 0)
						mtotals.update('executing', -1, 0)

						try:
							start, *messages, stop = xacts.pop(channel)
						except ValueError:
							pass
						else:
							traps.eox(monitor, stop, start, messages, status['channel'])
					elif evtype == 'transaction-started':
						metrics.update('executing', 1, 0)
						mtotals.update('executing', 1, 0)

			# Calculate change in time for Metrics.commit.
			next_time = time()
			# millisecond precision
			elapsed = (next_time.decrease(last).select('millisecond') or 1)
			elapsed /= 1000 # convert to float seconds
			last = next_time

			# Update duration and any other altered fields.
			for m in monitors:
				mm = m.metrics
				deltas = set(mm.changes())
				mm.commit(elapsed)
				mm.trim(window)
				stctl.update(m, m.delta(deltas))

			tdeltas = set(mtotals.changes())
			mtotals.commit(elapsed)
			mtotals.trim(window)

			summary.title(title, '/'.join(map(str, queue.status())))
			stctl.frame(summary)
			stctl.update(summary, summary.delta(tdeltas))
			stctl.flush()
		else:
			pass
	finally:
		ioa.__exit__(None, None, None) # Exception has the same effect.
		for lid in statusd:
			try:
				os.killpg(statusd[lid]['pid'], signal.SIGKILL)
			except (KeyError, ProcessLookupError):
				pass
			else:
				exit_status = execution.reap(status['pid'], options=0)
