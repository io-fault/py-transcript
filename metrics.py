"""
# Data structures for storing and combining status metrics for progress notifications.
"""
from ..context.tools import struct

@struct()
class Work:
	"""
	# Work unit progress metrics.

	# [ Properties ]
	# /w_prepared/
		# Number of Work Units that will be performed.
	# /w_failed/
		# Number of Work Units that indicated failure.
	# /w_granted/
		# Number of Work Units that were already considered complete.
		# Tests skipped or cached results.
	# /w_executed/
		# Number of Work Units executed that did not indicate failure.
	"""
	m_symbol = '%'

	w_prepared: int = 0
	w_executed: int = 0
	w_granted: int = 0
	w_failed: int = 0

	@property
	def w_total(self) -> int:
		"""
		# Number of failed, executed, or granted Works Units.
		"""
		return self.w_failed + self.w_executed + self.w_granted

	@property
	def w_executing(self) -> int:
		"""
		# Number of prepared work units that were not granted and
		# have not completed or failed.
		"""
		return self.w_prepared - self.w_total

	def __str__(self):
		return ''.join(map(str,
			[
				self.w_executed,
				'+', self.w_granted,
				'-', self.w_failed,
				'/', self.w_prepared,
			])
		)

	def empty(self) -> bool:
		if not (self.w_prepared, self.w_executed, self.w_granted, self.w_failed) == (0, 0, 0, 0):
			return False

		return True

	def __add__(self, op):
		return self.__class__(
			self.w_prepared + op.w_prepared,
			self.w_executed + op.w_executed,
			self.w_granted + op.w_granted,
			self.w_failed + op.w_failed,
		)

	@classmethod
	def split(Class, text:str):
		try:
			x, prepared = text.split('/', 1)
		except ValueError:
			prepared = None
		else:
			prepared = int(prepared)

		try:
			executed, x = x.split('+', 1)
		except ValueError:
			executed = x

		if executed[:1] == '#':
			executed = executed[1:]

		executed = int(executed)
		granted, failed = map(int, x.split('-', 1))

		return Class(prepared, executed, granted, failed)

@struct()
class Advisory:
	"""
	# Advisory messaging metrics.

	# [ Properties ]
	# /m_notices/
		# Messages emitted by the Work Units that were neither warnings or errors.
	# /m_warnings/
		# Warnings issued by the Work Units to the Application.
	# /m_errors/
		# Errors issued by the Work Units to the Application.
	"""
	m_symbol = '@'

	m_notices: int = 0
	m_warnings: int = 0
	m_errors: int = 0

	@property
	def m_total(self) -> int:
		"""
		# Total number of errors, warnings, and notices.
		"""
		return self.m_errors + self.m_warnings + self.m_notices

	def __str__(self):
		return ''.join(map(str, [
			'', self.m_notices,
			"!", self.m_warnings,
			"*", self.m_errors,
		]))

	def empty(self) -> bool:
		return (self.m_notices, self.m_warnings, self.m_errors) == (0, 0, 0)

	def __add__(self, op):
		return self.__class__(
			self.m_notices + op.m_notices,
			self.m_warnings + op.m_warnings,
			self.m_errors + op.m_errors,
		)

	@classmethod
	def split(Class, text:str):
		p = []
		parts = [
			text.find('!'),
			text.find('*'),
			len(text),
		]

		x = 0
		for y in parts:
			if y == -1:
				y = parts[-1]
			p.append(int(text[x:y]))
			x = y + 1

		return Class(*p)

@struct()
class Resource:
	"""
	# Resource usage metrics.

	# [ Properties ]
	# /r_divisions/
		# The number of system processes that used the measured resources.
	# /r_time/
		# The sum of the duration of all divisions.
	# /r_process/
		# Processor usage of the divisions.
	# /r_memory/
		# Memory usage of the divisions.
	"""
	m_symbol = '$'

	r_divisions: int = 0
	r_memory: int = 0
	r_process: int = 0
	r_time: int = 0

	def __str__(self) -> str:
		return ''.join([
			str(self.r_process),
			':', str(self.r_time),
			'#', str(self.r_memory),
			'/', str(self.r_divisions),
		])

	def empty(self) -> bool:
		return (self.r_divisions, self.r_memory, self.r_process, self.r_time) == (0, 0, 0, 0)

	def __add__(self, op):
		return self.__class__(
			self.r_divisions + op.r_divisions,
			self.r_memory + op.r_memory,
			self.r_process + op.r_process,
			self.r_time + op.r_time,
		)

	@classmethod
	def split(Class, text:str):
		p = []
		parts = [
			text.find(':'),
			text.find('#'),
			text.find('/'),
			len(text),
		]

		x = 0
		for y in parts:
			if y == -1:
				y = parts[-1]
			p.append(int(text[x:y]))
			x = y + 1

		return Class(p[-1], p[-2], p[0], p[1])

@struct()
class Procedure:
	"""
	# Collection of metrics regarding the status of an Abstract Procedure.

	# [ Properties ]
	# /work/
		# Procedure Work Unit progress.
	# /msg/
		# Procedure message counters.
	# /usage/
		# Procedure resource usage.
	"""

	work: Work
	msg: Advisory
	usage: Resource

	def __iter__(self):
		for x in [
			('work', self.work),
			('msg', self.msg),
			('usage', self.usage),
		]:
			if x is not None:
				yield x

	@classmethod
	def create(Class):
		"""
		# Create an empty Procedure.
		"""
		return Class(Work(), Advisory(), Resource())

	def __getitem__(self, path):
		selection = self

		try:
			for a in path:
				selection = getattr(selection, a)
		except AttributeError:
			raise IndexError('.'.join(path))
		else:
			return selection

	def __add__(self, operand):
		return self.__class__(
			self.work + operand.work if self.work is not None else operand.work,
			self.msg + operand.msg if self.msg is not None else operand.msg,
			self.usage + operand.usage if self.usage is not None else operand.usage,
		)

	_metrics_symbols = {
		'%': ('work', Work),
		'@': ('msg', Advisory),
		'$': ('usage', Resource),
	}

	@classmethod
	def structure(Class, text:str):
		"""
		# Structure progress text into a &Metrics instance.
		"""

		fields = {'work': Work(), 'usage': Resource(), 'msg': Advisory()}
		for x in text.split():
			if x[:1] in Class._metrics_symbols:
				group, typ = Class._metrics_symbols[x[:1]]
				fields[group] = typ.split(x[1:])

		return Class(**fields)

	def sequence(self) -> str:
		"""
		# Return the components making up the serialized string.
		"""
		s = []

		for c in '%@$':
			field = self._metrics_symbols[c][0]
			attrv = getattr(self, field, None)
			if attrv is not None and not attrv.empty():
				s.append(c+str(attrv))

		return ' '.join(s)
