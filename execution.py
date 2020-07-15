"""
# System process status display using transaction frames.
"""
import os
import collections
import typing

from ..context import tools
from ..terminal import palette
from . import terminal

def title(category, dimensions):
	"""
	# Form a title string from an execution plan's category and dimensions.
	"""
	return str(category) + '[' + ']['.join(dimensions) + ']'

def r_title(value):
	c, d = value
	return [('plain', title(c, d))]

_metric_units = [
	('', '', 0),
	('kilo', 'k', 3),
	('mega', 'M', 6),
	('giga', 'G', 9),
	('tera', 'T', 12),
	('peta', 'P', 15),
	('exa', 'E', 18),
	('zetta', 'Z', 21),
	('yotta', 'Y', 24),
]

def _precision(count):
	index = 0
	for pd in _metric_units:
		count //= (10**3)
		if count < 1000:
			return pd
	return pd

def _strings(value, formatting="{:.1f}".format):
	suffix, power = _precision(value)[1:]
	r = value / (10**power)
	return (formatting(r), suffix)

def r_count(field, value):
	if isinstance(value, str) or (value < 100000 and not isinstance(value, float)):
		n = str(value)
		unit = ''
	else:
		n, unit = _strings(value)

	return [
		(field, n),
		('unit-label', unit)
	]

def r_usage(value, color='blue'):
	yield from r_count('usage', value or 0.0)
	return

	for count in value[:-1]:
		yield from r_count('usage', count)
		yield ('plain', '/')

	count = value[-1]
	yield from r_count('usage', count)

def r_label(value):
	start, keycode, end = value
	return [
		('Label', start),
		('Label-Emphasis', keycode),
		('Label', end),
	]

# Display order.
_order = [
	('usage', 8),
	('executing', 8),
	('failed', 8),
	('finished', 8),
]

_formats = [
	('u', "usage", 'violet', r_usage),
	('x', "executing", 'orange', tools.partial(r_count, 'executing')),
	('f', "failed", 'red', tools.partial(r_count, 'failed')),
	('d', "finished", 'green', tools.partial(r_count, 'finished')),
]

def configure(order, formats):
	l = terminal.Layout(order)
	t = terminal.Theme(terminal.matrix.Type.normal_render_parameters)
	t.implement('duration', terminal.Theme.r_duration)
	t.implement('title', r_title)
	t.define('duration', textcolor=palette.colors['white'])
	t.define('unit-label', textcolor=palette.colors['gray'])
	t.define('data-rate-receive', textcolor=palette.colors['terminal-default'])
	t.define('data-rate-transmit', textcolor=palette.colors['terminal-default'])
	t.define('data-rate', textcolor=palette.colors['gray'])

	for (k, width), (keycode, label, color, fn) in zip(order, formats):
		if fn is not None:
			t.implement(k, fn)
		t.define(k, textcolor=palette.colors[color])
		l.label(k, label or None)

	return t, l

ATheme, ALayout = configure(_order, _formats)

def aggregate(lanes=1, width=80, layout=ALayout, theme=ATheme):
	"""
	# Construct a monitor controller for execution aggregation.
	"""
	stctl = terminal.setup(lanes+1)

	lanes_seq = [
		terminal.Monitor(theme, layout, stctl.allocate((0, i), width=width))
		for i in range(lanes)
	]
	totals = terminal.Monitor(theme, layout, stctl.allocate((0, lanes), width=width))

	return stctl, lanes_seq, totals

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

def _transmit(pack, output, stctl, monitor, channel):
	m = monitor.metrics
	cells, mss = monitor.snapshot()
	synop = monitor._title[0] + ': ' + mss + stctl.context.reset_text().decode('utf-8')

	output.write(pack((channel, transaction(synop, m.duration))))

def dispatch(error, output, control, monitors, summary, title, queue, trap, plan, range=range, next=next):
	"""
	# Execute a sequence of system commands while displaying their status
	# according to the transaction messages they emit to standard out.

	# Commands are executed simultaneously so long as a monitor is available to display
	# their status.
	"""
	import signal
	from . import io
	from ..system import query
	from ..system import execution
	from ..time.sysclock import now, elapsed
	from ..status import frames

	unpack, pack = frames.stdio()
	hostname = query.hostname()
	total_messages = 0
	message_count = 0
	nmonitors = len(monitors)
	ioa = io.FrameArray(unpack)

	stctl = control
	available = collections.deque(range(nmonitors))
	statusd = {}
	processing = True
	last = elapsed()
	summary.title(title, '*')
	mtotals = summary.metrics

	try:
		ioa.__enter__()
		while processing:
			if available:
				# Open processing lanes take from queue.
				for ident in queue.take(len(available)):
					lid = available.popleft()
					kii = iter(plan(ident))

					status = statusd[lid] = {
						'source': ident,
						'process-queue': kii,
						'start-time': elapsed(),
						'transactions': collections.defaultdict(list),
					}

					monitor = monitors[lid]
					monitor.metrics.clear()

					next_channel = _launch(status)
					if next_channel is None:
						queue.finish(status['source'])
						stctl.clear(monitor)
						available.append(lid)
						continue

					monitor.title(next_channel[1], *next_channel[2])
					ioa.connect(lid, next_channel[0])
					stctl.clear(monitor)
					stctl.frame(monitor)
					stctl.update(monitor, monitor.render())

				stctl.flush()
				if queue.terminal():
					if not statusd:
						# Queue has nothing and statusd is empty? EOF.
						processing = False
						continue

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
					_transmit(pack, output, stctl, monitor, status['channel'])
					output.flush()

					next_channel = _launch(status)
					if next_channel is not None:
						ioa.connect(lid, next_channel[0])
						stctl.clear(monitor)
						monitor.metrics.clear()
						monitor.title(next_channel[1], *next_channel[2])
						stctl.frame(monitor)
						stctl.update(monitor, monitor.render())
						continue

					queue.finish(status['source'])
					del statusd[lid]
					available.append(lid)

					summary.title(title, '/'.join(map(str, queue.status())))
					stctl.frame(summary)
					stctl.update(summary, summary.render())
					status.clear()
					stctl.clear(monitor)
					continue

				nframes = len(sframes)
				message_count += nframes

				for channel, msg in sframes:
					evtype = msg.msg_event.symbol
					xacts[channel].append(msg)

					if evtype == 'transaction-stopped':
						metrics.update('executing', -1)
						mtotals.update('executing', -1)

						try:
							start, *messages, stop = xacts.pop(channel)
						except ValueError:
							pass
						else:
							start_data = start.msg_parameters['data']
							stop_data = stop.msg_parameters['data']

							u = stop_data.get_parameter('user')
							s = stop_data.get_parameter('system')
							for m in (metrics, mtotals):
								#m.update('process-time', u)
								#m.update('kernel-time', s)
								m.update('usage', u + s)

							start_time = start_data.get_parameter('time-offset')
							stop_time = stop_data.get_parameter('time-offset')

							duration = (stop_time - start_time)

							exit_code = stop_data.get_parameter('status')
							if exit_code != 0:
								metrics.update('failed', 1)
								mtotals.update('failed', 1)
								#trap(output, xcontext, channel, stop_data, start_data, messages)
							else:
								metrics.update('finished', 1)
								mtotals.update('finished', 1)
					elif evtype == 'transaction-started':
						metrics.update('executing', 1)
						mtotals.update('executing', 1)

			next_time = elapsed()
			duration = (next_time.decrease(last).select('millisecond') or 1)
			last = next_time
			duration /= 1000 # convert to float seconds

			for m in monitors:
				mm = m.metrics
				deltas = set(mm.changes())
				mm.commit(duration)
				mm.trim()
				stctl.update(m, m.delta(deltas))

			tdeltas = set(mtotals.changes())
			mtotals.commit(duration)
			mtotals.trim()

			#totals['usage'] = [100*utime/duration, 100*stime/duration]
			summary.title(title, '/'.join(map(str, queue.status())))
			stctl.frame(summary)
			stctl.update(summary, summary.delta(tdeltas))
			stctl.flush()
		else:
			pass
	finally:
		summary.metrics.clear()
		ioa.__exit__(None, None, None) # Exception has the same effect.
		error.flush()
		for lid in statusd:
			try:
				os.killpg(statusd[lid]['pid'], signal.SIGKILL)
			except (KeyError, ProcessLookupError):
				pass
			else:
				exit_status = execution.reap(status['pid'], options=0)
