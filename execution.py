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

_metric_units = [
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
	if isinstance(value, str) or value < 100000:
		n = str(value)
		unit = ''
	else:
		n, unit = _strings(value)

	return [
		(field, n),
		('unit-label', unit)
	]

def r_usage(value, color='blue'):
	if not value:
		return

	for t, count in value[:-1]:
		yield ('usage', "{:.1f}".format(count))
		yield ('usage-context-'+t, t)
		yield ('plain', '/')

	t, count = value[-1]
	yield ('usage', "{:.1f}".format(count))
	yield ('usage-context-'+t, t)

def r_label(value):
	start, keycode, end = value
	return [
		('Label', start),
		('Label-Emphasis', keycode),
		('Label', end),
	]

# Display order.
_order = [
	('title', -32),
	('duration', 6),
	('usage', 32),
	('executing', 8),
	('failed', 8),
	('finished', 8),
]

_formats = [
	('i', "", 'white', None), # Title
	('t', "duration", 'white', terminal.Theme.r_duration),
	('u', "usage", 'violet', r_usage),
	('x', "executing", 'yellow', tools.partial(r_count, 'executing')),
	('f', "failed", 'red', tools.partial(r_count, 'failed')),
	('d', "finished", 'green', tools.partial(r_count, 'finished')),
]

def configure(order, formats):
	l = terminal.Layout(order)
	t = terminal.Theme(terminal.matrix.Type.normal_render_parameters)
	t.define('unit-label', textcolor=palette.colors['gray'])
	t.define('usage-context-p', textcolor=palette.colors['gray'])
	t.define('usage-context-k', textcolor=palette.colors['gray'])
	t.define('usage-context-receive', textcolor=palette.colors['gray'])
	t.define('usage-context-transmit', textcolor=palette.colors['gray'])
	t.define('data-rate-receive', textcolor=palette.colors['terminal-default'])
	t.define('data-rate-transmit', textcolor=palette.colors['terminal-default'])
	t.define('data-rate', textcolor=palette.colors['gray'])

	for (k, width), (keycode, label, color, fn) in zip(order, formats):
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

def deltas(trap, transactions, counts, frames, log=(lambda x: None)):
	xacts = transactions
	started = 0
	exits = 0
	failed = 0
	utime = 0
	stime = 0

	for channel, msg in frames:
		evtype = msg.msg_event.symbol
		counts[evtype] += 1
		xacts[channel].append(msg)

		if evtype == 'transaction-stopped':
			exits += 1
			start, *messages, stop = xacts.pop(channel)
			record = (start, messages, stop)

			start_data = start.msg_parameters['data']
			stop_data = stop.msg_parameters['data']

			utime += stop_data.get_parameter('user')
			stime += stop_data.get_parameter('system')

			start_time = start_data.get_parameter('time-offset')
			stop_time = stop_data.get_parameter('time-offset')
			duration = stop_time - start_time

			exit_code = stop_data.get_parameter('status')
			if exit_code != 0:
				failed += 1
				trap(channel, record)

			log((channel, record, duration))
		elif evtype == 'transaction-started':
			started += 1

	yield ('started', started)
	yield ('utime', utime)
	yield ('stime', stime)
	yield ('finished', exits - failed)
	yield ('failed', failed)

def singledispatch(error, output, controls, trap, invocations):
	"""
	# Execute a sequence of system commands while displaying their status
	 according to the transaction messages they emit to standard out.
	"""
	from ..system import query
	from ..time.sysclock import now, elapsed
	from ..status import frames
	from .io import spawnframes

	pack = frames.stdio()[1]
	hostname = query.hostname()
	total_messages = 0
	message_count = 0

	stctl, monitors, tmonitor = controls
	monitor, = monitors

	try:
		for category, dimensions, xqual, xcontext, ki in invocations:
			status = {
				'executing': 0,
				'failed': 0,
				'finished': 0,
				'usage': [('p', 0.0), ('k', 0.0)],
				'duration': 0.0,
				'title': title(category, dimensions),
				'start-time': elapsed(),
				'type': category,
				'channel': xqual,
			}

			utime = 0.0
			stime = 0.0

			monitor.update(status)
			stctl.flush()

			counts = collections.Counter()
			xacts = collections.defaultdict(list)

			start_offset = elapsed()
			framelists = spawnframes(ki)
			sf_protocol = next(framelists)

			total_messages += message_count
			message_count = len(sf_protocol)

			for sframes in framelists:
				message_count += len(sframes)
				for channel, msg in sframes:
					evtype = msg.msg_event.symbol
					counts[evtype] += 1

					xacts[channel].append(msg)

					if evtype == 'transaction-stopped':
						start, *messages, stop = xacts.pop(channel)
						start_data = start.msg_parameters['data']
						stop_data = stop.msg_parameters['data']

						utime += stop_data.get_parameter('user')
						stime += stop_data.get_parameter('system')

						start_time = start_data.get_parameter('time-offset')
						stop_time = stop_data.get_parameter('time-offset')

						duration = (stop_time - start_time)

						exit_code = stop_data.get_parameter('status')
						if exit_code != 0:
							status['failed'] += 1
							trap(output, xcontext, channel, stop_data, start_data, messages)

				status['finished'] = counts['transaction-stopped'] - status['failed']
				status['executing'] = str(counts['transaction-started'] - status['finished'])

				duration = (elapsed().decrease(start_offset).select('millisecond') or 1)
				duration /= 1000 # convert to float seconds
				status['usage'] = [('p', 100*utime/duration), ('k', 100*stime/duration)]
				status['duration'] = duration

				monitor.update(status)
				stctl.reflect(monitor)
				stctl.flush()

			status['finished'] = str(status['finished']).rjust(5, ' ')
			status['title'] = status['type']
			monitor.update(status)
			cells, mss = monitor.snapshot()
			synop = status['type'] + ': ' + mss + stctl.context.reset_text().decode('utf-8')
			output.write(pack((status['channel'], transaction(synop, duration))))
			output.flush()
	finally:
		stctl.clear(monitor)
		stctl.flush()
		error.flush()

def _launch(status, stderr=2, stdin=0):
	status.update({
		'pid': 0,
		'failed': 0,
		'finished': 0,
		'executing': 0,
		'duration': 0.0,
		'stime': 0.0,
		'utime': 0.0,
		'usage': [('p', 0.0), ('k', 0.0)],
		'counts': collections.Counter(),
		'messages': 0,
		'transactions': collections.defaultdict(list),
	})

	try:
		category, dimensions, xqual, xcontext, ki = next(status['process-queue'])
		status['type'] = category
		status['title'] = title(category, dimensions)
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

	return rfd

def _transmit(pack, output, stctl, monitor, status):
	for k in ['finished', 'executing', 'failed']:
		status[k] = str(status[k]).rjust(5, ' ')

	monitor.update(status)
	cells, mss = monitor.snapshot()
	synop = status['type'] + ': ' + mss + stctl.context.reset_text().decode('utf-8')

	output.write(pack((status['channel'], transaction(synop, status['duration']))))

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
	totals = {
		'pid': 0,
		'executing': 0,
		'failed': 0,
		'finished': 0,
		'usage': [('p', 0.0), ('k', 0.0)],
		'duration': 0.0,
		'start-time': elapsed(),
		'stime': 0.0,
		'utime': 0.0,
		'type': 'aggregate',
		'title': title + "[*]",
	}
	summary.update(totals)

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
					}

					next_channel = _launch(status)
					if next_channel is None:
						queue.finish(status['source'])
						available.append(lid)
						continue
					else:
						status['start-time'] = elapsed()
						ioa.connect(lid, next_channel)

					monitor = monitors[lid]
					monitor.update(status)
					stctl.clear(monitor)
					stctl.reflect(monitor)

				# Queue processed, but monitors are still available?
				for lid in available:
					stctl.clear(monitors[lid])

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
				counts = status['counts']
				srcid = status['source']
				monitor = monitors[lid]

				if sframes is None:
					# Closed.
					pid = status['pid']
					exit_status = execution.reap(pid, options=0)

					# Send final snapshot to output. (stdout)
					_transmit(pack, output, stctl, monitor, status)
					output.flush()

					next_channel = _launch(status)
					if next_channel is not None:
						status['start-time'] = elapsed()
						ioa.connect(lid, next_channel)
						stctl.clear(monitor)
						stctl.reflect(monitor)
						continue

					queue.finish(status['source'])
					del statusd[lid]
					available.append(lid)

					totals['title'] = "%s[%d/%d]" %((title,)+queue.status())
					summary.update(totals)
					stctl.reflect(summary)
					status.clear()
					continue

				nframes = len(sframes)
				message_count += nframes

				for channel, msg in sframes:
					evtype = msg.msg_event.symbol
					counts[evtype] += 1
					xacts[channel].append(msg)

					if evtype == 'transaction-stopped':
						totals['executing'] -= 1
						status['executing'] -= 1

						try:
							start, *messages, stop = xacts.pop(channel)
						except ValueError:
							pass
						else:
							start_data = start.msg_parameters['data']
							stop_data = stop.msg_parameters['data']

							u = stop_data.get_parameter('user')
							s = stop_data.get_parameter('system')
							status['utime'] += u
							status['stime'] += s
							totals['utime'] += u
							totals['stime'] += s

							start_time = start_data.get_parameter('time-offset')
							stop_time = stop_data.get_parameter('time-offset')

							duration = (stop_time - start_time)

							exit_code = stop_data.get_parameter('status')
							if exit_code != 0:
								status['failed'] += 1
								totals['failed'] += 1
								#trap(output, xcontext, channel, stop_data, start_data, messages)
							else:
								totals['finished'] += 1
								status['finished'] += 1
					elif evtype == 'transaction-started':
						totals['executing'] += 1
						status['executing'] += 1

				start_offset = status['start-time']
				utime = status['utime']
				stime = status['stime']
				duration = (elapsed().decrease(start_offset).select('millisecond') or 1)
				duration /= 1000 # convert to float seconds
				status['usage'] = [('p', 100*utime/duration), ('k', 100*stime/duration)]
				status['duration'] = duration

				monitor.update(status)
				stctl.reflect(monitor)

			utime = totals['utime']
			stime = totals['stime']
			duration = (elapsed().decrease(totals['start-time']).select('millisecond') or 1)
			duration /= 1000 # convert to float seconds
			totals['usage'] = [('p', 100*utime/duration), ('k', 100*stime/duration)]
			totals['duration'] = duration
			totals['title'] = "%s[%d/%d]" %((title,)+queue.status())
			summary.update(totals)
			stctl.reflect(summary)
			stctl.flush()
		else:
			pass
	finally:
		ioa.__exit__(None, None, None) # Exception has the same effect.
		error.flush()
		for lid in statusd:
			try:
				os.killpg(statusd[lid]['pid'], signal.SIGKILL)
			except (KeyError, ProcessLookupError):
				pass
			else:
				exit_status = execution.reap(status['pid'], options=0)
