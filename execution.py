"""
# System process status display using transaction frames.
"""
import os
import collections
import typing

from ..terminal import palette
from . import terminal

def title(category, dimensions):
	"""
	# Form a title string from an execution plan's category and dimensions.
	"""
	return str(category) + '[' + ']['.join(dimensions) + ']'

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
	('title', -24),
	('duration', 6),
	('usage', 32),
	('executing', 6),
	('failed', 6),
	('finished', 6),
]

_formats = [
	('i', "", 'white', None), # Title
	('t', "duration", 'white', terminal.Theme.r_duration),
	('u', "usage", 'violet', r_usage),
	('x', "executing", 'yellow', None),
	('f', "failed", 'red', None),
	('d', "finished", 'green', None),
]

def configure(order, formats):
	l = terminal.Layout(order)
	t = terminal.Theme(terminal.matrix.Type.normal_render_parameters)
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

def dispatch(error, output, control, monitors, summary, queue, trap, plan, range=range, next=next):
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
		'title': "SUMMARY[*]",
	}
	summary.update(totals)

	try:
		ioa.__enter__()
		while processing:
			if available:
				# Open processing lanes take from queue.
				for ident in queue.take(len(available)):
					lid = available.popleft()
					category, dimensions, xqual, xcontext, ki = plan(ident)

					rfd, wfd = os.pipe()
					pid = ki.spawn(fdmap=[(0,0), (wfd,1), (2,2)])
					ioa.connect(lid, rfd)
					os.close(wfd)

					status = statusd[lid] = {
						'pid': pid,
						'executing': 0,
						'failed': 0,
						'finished': 0,
						'usage': [('p', 0.0), ('k', 0.0)],
						'duration': 0.0,
						'start-time': elapsed(),
						'transactions': collections.defaultdict(list),
						'stime': 0.0,
						'utime': 0.0,
						'source': ident,
						'counts': collections.Counter(),
						'messages': 0,
						'type': category,
						'title': title(category, dimensions),
						'channel': xqual,
					}

					monitor = monitors[lid]
					monitor.update(status)
					stctl.clear(monitor)
					stctl.reflect(monitor)

				if queue.terminal() and not statusd:
					# Queue has nothing and statusd is empty? EOF.
					processing = False
					stctl.flush()
					continue

				stctl.flush()

			# Cycle through sources, flush when complete.
			for lid, sframes in ioa:
				status = statusd[lid]
				xacts = status['transactions']
				counts = status['counts']
				srcid = status['source']
				monitor = monitors[lid]

				if sframes is None:
					# Closed.
					queue.finish(status['source'])
					del statusd[lid]
					available.append(lid)
					exit_status = execution.reap(status['pid'], options=0)

					# Send final snapshot to output. (stdout)
					status['finished'] = str(status['finished']).rjust(5, ' ')
					monitor.update(status)
					cells, mss = monitor.snapshot()
					synop = status['type'] + ': ' + mss + stctl.context.reset_text().decode('utf-8')

					output.write(pack((status['channel'], transaction(synop, duration))))
					output.flush()
					status.clear()
					continue

				nframes = len(sframes)
				message_count += nframes

				for channel, msg in sframes:
					evtype = msg.msg_event.symbol
					counts[evtype] += 1
					xacts[channel].append(msg)

					if evtype == 'transaction-stopped':
						start, *messages, stop = xacts.pop(channel)
						start_data = start.msg_parameters['data']
						stop_data = stop.msg_parameters['data']

						status['utime'] += stop_data.get_parameter('user')
						status['stime'] += stop_data.get_parameter('system')

						totals['utime'] += stop_data.get_parameter('user')
						totals['stime'] += stop_data.get_parameter('system')

						start_time = start_data.get_parameter('time-offset')
						stop_time = stop_data.get_parameter('time-offset')

						duration = (stop_time - start_time)

						exit_code = stop_data.get_parameter('status')
						if exit_code != 0:
							status['failed'] += 1
							totals['failed'] += 1
							trap(output, xcontext, channel, stop_data, start_data, messages)
						else:
							totals['finished'] += 1
							totals['executing'] -= 1
					elif evtype == 'transaction-started':
						totals['executing'] += 1

				status['finished'] = counts['transaction-stopped'] - status['failed']
				status['executing'] = str(counts['transaction-started'] - status['finished'])

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
