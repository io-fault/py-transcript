"""
# System process status display using transaction frames.
"""
import os
import sys
import collections
import typing
import signal
from dataclasses import dataclass

from ..context import tools
from ..time.sysclock import now, elapsed as time
from ..system import execution
from ..status import frames

from . import io

def _launch(status, stderr=2, stdin=0):
	# Get the next invocation from the iterator and spawn it.
	try:
		category, dimensions, xcontext, ki = next(status['process-queue'])
		status['category'] = category
		status['identifier'] = xcontext
	except StopIteration:
		return None

	rfd, wfd = os.pipe()
	try:
		status['pid'] = ki.spawn(fdmap=[(0,0), (wfd,1), (2,2)])
	except:
		os.close(rfd)
		raise
	finally:
		os.close(wfd)

	return (rfd, category, dimensions)

def _field(key, ext, default=None):
	# Retrieve the field value or default if not present or is an empty string.
	if key in ext:
		return ext[key][0] or default
	else:
		return default

def _closed(failed, start, stop, xframes, extension, /,
		executed='<>', failure='><',
		ts=tools.partial(_field, '@timestamp'),
	):
	"""
	# Join a start and stop frame.
	"""
	ext = extension
	ext.update(start.f_extension)
	ext.update(stop.f_extension)

	# Set duration from start and stop timestamps.
	if '@duration' not in ext:
		start_time = int(ts(start.f_extension, 0))
		stop_time = int(ts(stop.f_extension, 0))
		ext['@duration'] = [str(-(stop_time - start_time))]

	# Frame sources should provide non-zero metrics on both sides.
	metrics = start.f_extension.get('@metrics', []) + stop.f_extension.get('@metrics', [])
	metrics = [x for x in metrics if x.strip()]
	if metrics:
		ext['@metrics'] = metrics

	if '@frames' in ext and not ext['@frames']:
		del ext['@frames']

	# If failure is indicated, the failed transaction type should be preferred.
	if failed:
		typ = failure
	else:
		# Executed or Granted. Use the designated type if any.
		typ = ext.pop('@frame-type', [executed])[0]

	return frames.compose(typ, stop.f_image, stop.f_channel, ext)

def _open_frame(status, fcompose=frames.compose):
	ctx = status['category']
	ts = now().select('iso')

	ext = {
		'@timestamp': [str(time())],
	}
	if status['identifier']:
		ctx = status['identifier']
		ext['@transaction'] = [ctx]

	return fcompose('->', ctx + ': ' + ts, None, ext)

def dispatch(meta, log,
		plan, control, monitors, summary, title, queue,
		opened=False,
		select=(lambda t,m,f: False), alerts=True,
		window=8, frequency=64,
		kill=os.killpg, range=range, next=next
	):
	"""
	# Execute a sequence of system commands while displaying their status
	# according to the transaction messages they emit to standard out.

	# Commands are executed simultaneously so long as a monitor is available to display
	# their status.
	"""
	closetypes = {
		(False, True): '<>',
		(False, False): '><',
	}

	from .metrics import Procedure
	zero = Procedure.create()

	total_messages = 0
	message_count = 0
	ioa = io.FrameArray(timeout=frequency)

	available = collections.deque(range(len(monitors)))
	statusd = {}
	processing = True
	last = time()
	summary.reset(last, zero)
	for m in monitors:
		m.reset(last, zero)
	mtotal = zero

	summary.title(title, '/'.join(map(str, queue.status())))
	control.install(summary)

	try:
		ioa.__enter__()
		while processing:
			if available:
				# Open processing lanes take from queue.
				for ident in queue.take(len(available)):
					lid = available.popleft()
					iki = iter(plan(ident))

					status = statusd[lid] = {
						'source': ident,
						'process-queue': iki,
						'transactions': collections.defaultdict(list),
					}

					monitor = monitors[lid]
					monitor.reset(last, zero)

					next_channel = _launch(status)
					if next_channel is None:
						queue.finish(status['source'])
						available.append(lid)
						del statusd[lid]
						continue

					monitor.title(next_channel[1], *next_channel[2])
					ioa.connect(lid, next_channel[0])
					control.install(monitor)

					if opened:
						log.emit(_open_frame(status))

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
									# continues for-loop, check next list.
									break
								else:
									# Per-channel open transactions.
									status['transactions'] = collections.defaultdict(list)
									xlid = available.popleft()
									statusd[xlid] = status
									monitor = monitors[xlid]
									monitor.reset(time(), zero)

									monitor.title(next_channel[1], *next_channel[2])
									ioa.connect(xlid, next_channel[0])
									control.install(monitor)

									if opened:
										log.emit(_open_frame(status))
									log.flush()
							else:
								# No more availability, exit for-sources.
								break

			# Located before possible waits in &ioa.__iter__,
			# but not directly after to allow seamless transitions.
			control.flush()

			# Calculate change in time for Metrics.commit.
			next_time = time()

			# Cycle through sources, flush when complete.
			for lid, sframes in ioa:
				monitor = monitors[lid]
				status = statusd[lid]
				xacts = status['transactions']
				srcid = status['source']

				if sframes is None:
					# Closed.
					pdelta = execution.reap(status['pid'], options=0)

					# Send final snapshot to log.
					ftype = closetypes.get((opened, pdelta.status == 0), '<-')
					xf = monitor.frame(ftype, status['identifier'])
					log.emit(xf)
					log.flush()

					next_channel = _launch(status)
					monitor.reset(next_time, zero)

					if next_channel is not None:
						ioa.connect(lid, next_channel[0])
						monitor.title(next_channel[1], *next_channel[2])
						control.install(monitor)
						if opened:
							log.emit(_open_frame(status))
						continue

					queue.finish(status['source'])
					del statusd[lid]
					available.append(lid)

					qs = queue.status()
					summary.title(title, '/'.join(map(str, (qs[0]-len(statusd), qs[1]))))
					control.install(summary)
					status.clear()
					continue

				nframes = len(sframes)
				message_count += nframes

				pdelta = zero
				for f in sframes:
					channel = f.f_channel
					evtype = f.f_event.symbol
					ext = f.f_extension or {}
					xid = (channel, tuple(ext.get('@transaction', ())))

					# Update the monitors view.
					delta = zero
					for x in ext.get('@metrics', ()):
						delta += Procedure.structure(x)
					pdelta += delta

					if evtype == 'transaction-started':
						start_frame = f
						xframes = list()
						xacts[xid] = (f, xframes)
						rf = start_frame
						failure = None
					elif evtype == 'transaction-stopped':
						start_frame, xframes = xacts.pop(xid, (None, ()))
						failure = (delta.work.w_failed > 0)
						rf = _closed(failure, start_frame, f, xframes, {})
					else:
						start_frame, xframes = xacts.get(xid, (None, ()))
						rf = f
						failure = (evtype == 'transaction-failed')

					# Report the combined frame to log if selected.
					if select(None, delta, rf):
						log.emit(rf)
						log.flush()

					# Report the failures to meta if alerts are enabled.
					if failure and alerts:
						meta.emit(rf)
						fi = rf.f_extension.get('@failure-image', ())
						if len(fi) > 1:
							fi = iter(fi); next(fi)
							op = rf.f_extension.get('@operation', ())
							if op:
								meta.write('\n'.join(op))
								meta.write('\n')
							meta.write('\n'.join(fi))
							meta.write('\n')
						meta.flush()
					# Frame Processing
				mtotal += pdelta
				monitor.update(next_time, monitor.current + pdelta)

			last = next_time

			# Update duration and any other altered fields.
			for m in monitors:
				m.elapse(next_time)
				control.update(m, m.render())

			summary.update(next_time, mtotal)
			qs = queue.status()
			summary.title(title, '/'.join(map(str, (qs[0]-len(statusd), qs[1]))))
			control.update(summary, summary.render())
		else:
			pass
	except BrokenPipeError:
		pass
	finally:
		control.flush()
		ioa.__exit__(None, None, None) # Exception has the same effect.
		for lid in statusd:
			try:
				kill(statusd[lid]['pid'], signal.SIGKILL)
			except (KeyError, ProcessLookupError):
				pass
			else:
				exit_status = execution.reap(status['pid'], options=0)
