"""
# Transaction aggregation for Factored Project integration.

# Provides traps for the build and test portions of project integration.
"""
import itertools

from ..context import tools
from ..status import frames
from ..status import types
from ..system import files

# Protocol Identifiers for builds and tests.
test_report_protocol = 'http://if.fault.io/status/tests'
factor_report_protocol = 'http://if.fault.io/status/factors'

def closed_transaction_message(synopsis, duration, Message=types.Message):
	"""
	# Create aggregate status frame for the transaction.
	"""

	msg = Message.from_string_v1("transaction[><]: Execution", protocol=frames.protocol)
	msg.msg_parameters['envelope-fields'] = [synopsis]
	msg.msg_parameters['data'] = types.Parameters.from_pairs_v1([
		('duration', duration),
	])

	return msg

def select_failures(pack, monitor, stop, start, messages, channel):
	"""
	# Transaction processor selecting only build failures.
	"""
	stopd = stop.msg_parameters['data']
	startd = start.msg_parameters['data']
	if 'status' not in stopd:
		return ()

	cmd = startd.get_parameter('command')
	if stopd['status'] != 0:
		cmd = startd.get_parameter('command')
		factor = startd.get_parameter('factor')
		log = files.Path.from_absolute(startd.get_parameter('log'))
		duration = stopd['time-offset'] - startd['time-offset']
		return [(duration, cmd, stopd['status'], log, factor)]

	# Not failure or not a build command.
	return ()

def factor_report(transactions, chain=itertools.chain.from_iterable, protocol=factor_report_protocol):
	"""
	# Create a build report from a construction context's process.
	# Usually coupled with &select_failures to provide a report containing failed commands.
	"""

	r = types.Report.from_string_v1("process-failures[1]: build reports", protocol=protocol)

	times = []
	commands = []
	status = []
	factors = []
	logs = []

	for duration, cmd, st, log, factor in transactions:
		times.append(duration)
		commands.append(cmd)
		status.append(st)
		factors.append(factor)
		with log.fs_open('rb') as f:
			logs.append(f.read())

	r.r_parameters.specify([
		('v-sequence', 'integer', 'times', times),
		('v-sequence', 'integer', 'status', status),
		('v-sequence', 'integer', 'commands', [str(x[0]) for x in commands]),
		('v-sequence', 'string', 'factors', factors),
		('v-sequence', 'octets', 'errors', logs),
	])

	return r

def test_report(transactions, chain=itertools.chain.from_iterable, protocol=test_report_protocol):
	"""
	# Create a test report from a test process' transactions.
	"""

	s = [
		start.msg_parameters['data']['time-offset']
		for (start, m, stop) in transactions
		if 'fate' in stop.msg_parameters['data']
	]
	d = [stop.msg_parameters['data'] for (start, m, stop) in transactions]
	d = [x for x in d if 'fate' in x]
	r = types.Report.from_string_v1("fates[1]: test reports", protocol=protocol)

	r.r_parameters.specify([
		('v-sequence', 'integer', 'durations', [x['time-offset'] - y for (x, y) in zip(d, s)]),
		('v-sequence', 'string', 'tests', [x['identifier'] for x in d]),
		('v-sequence', 'string', 'fates', [x['fate'] for x in d]),
		('v-sequence', 'failure', 'failures', list(chain(x['failure'] or () for x in d))),
		('v-sequence', 'integer', 'failures/dimensions', [len(x['failure'] or ()) for x in d]),
	])

	return r

def emit_report(writers, report, pack, monitor, channel, aggregate, pid, status):
	"""
	# Message constructor for aggregated transactions.
	"""
	msg = closed_transaction_message(monitor.synopsis(), monitor.metrics.time)
	msg.msg_parameters['data'] = report(aggregate)

	packed = pack((channel, msg))
	for writer in writers:
		writer(packed)

def emitter(report, *writers):
	"""
	# Construct a call to &emit_report with the given report constructor
	# and &writers partially applied.
	"""
	return tools.partial(emit_report, writers, report)
