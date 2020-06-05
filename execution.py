"""
# System process status display using transaction frames.
"""
import collections

from ..terminal import palette
from . import terminal

ATheme = {
	'finished': ('green', "finished"),
	'failed': ('red', "failed"),
	'executing': ('violet', "executing"),
	'usage': ('blue', "usage"),
	'duration': ('orange', "duration"),
}

def aggregate(theme=ATheme):
	"""
	# Construct a monitor controller for execution aggregation.
	"""
	stctl = terminal.setup(1)
	stctl.initialize([
		'duration',
		'usage',
		'executing',
		'failed',
		'finished',
	])

	stctl.Key = stctl.Normal.apply(textcolor=palette.colors['foreground-adjacent'])
	stctl.Prefix = stctl.Normal

	for k, (v, fn) in theme.items():
		stctl.field_value_override[k] = stctl.Value.apply(textcolor=palette.colors[v])
		stctl.field_label_override[k] = fn

	return stctl

def duration_repr(seconds) -> str:
	if seconds < 60:
		return (seconds / 1.0, 's')
	elif seconds < (60*60):
		# minutes
		return (seconds / 60, 'm')

	hours = seconds / (60*60)
	if hours < 100:
		return (hours, 'h')

	return (hours / 24, 'd')

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

def dispatch(error, output, control, trap, invocations):
	"""
	# Execute a sequence of system commands while displaying their status
	# according to the transaction messages they emit to standard out.
	"""
	from ..system import query
	from ..time.sysclock import now, elapsed
	from .io import spawnframes
	from ..status import frames

	stctl = control
	hostname = query.hostname()
	pack = frames.stdio()[1]
	total_messages = 0
	message_count = 0

	try:
		for stitle, ftitle, xqual, xcontext, ki in invocations:
			status = {
				'executing': 0,
				'failed': 0,
				'finished': 0,
				'usage': ("({}) 0.0p/0.0k").format(hostname),
				'duration': "0.0s",
			}

			utime = 0.0
			stime = 0.0

			stctl.prefix(list(stctl.Normal.form(stitle)))
			stctl.update(status)

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
				status['usage'] = "({}) {:.1f}p/{:.1f}k".format(hostname, 100*utime/duration, 100*stime/duration)
				status['duration'] = "{:.1f}{}".format(*duration_repr(duration))
				stctl.update(status)

			stctl.prefix(())
			status['finished'] = str(status['finished']).rjust(5, ' ')
			stctl.field_values.update(status)
			output.write(pack((xqual, transaction(ftitle + ':' + stctl.flush(), duration))))
			output.flush()
	finally:
		stctl.clear()
		error.flush()
