"""
# Terminal support for status displays.
"""
import os
import io
import typing
import itertools
import collections

from ..context import tools
from ..terminal import matrix
from ..time import sysclock

def duration_repr(seconds) -> typing.Tuple[float, str]:
	if seconds < 60:
		return (seconds / 1.0, 's')
	elif seconds < (60*60):
		# minutes
		return (seconds / 60, 'm')

	hours = seconds / (60*60)
	if hours < 100:
		return (hours, 'h')

	return (hours / 24, 'd')

class Metrics(object):
	"""
	# Storage class for monitor field data.
	# Maintains a history along with a totals snapshot.
	"""

	def __init__(self):
		self.clear()

	def clear(self):
		self.duration = 0 # Implied time field.
		self.current = collections.defaultdict(int)
		self.snapshot = collections.defaultdict(int)
		self.history = []

	def recent(self, field:str):
		"""
		# Retrieve the value of the field as it's found within the history.
		"""
		i = 0
		for d, x in self.history:
			i += x[field]
		return i

	def rate(self, field:str):
		"""
		# The rate of the field with respect to the recent history.
		# The overall rate can be calculated with
		# (syntax/python)`m.total(field0) / m.duration`.
		"""
		i = 0
		t = 0
		for d, x in self.history:
			i += x.get(field, 0)
			t += d

		return i / t

	def overall(self, field:str):
		"""
		# The overall rate.
		"""
		return self.snapshot[field] / self.duration

	def average(self, field:str):
		"""
		# The average of the field within the history.
		"""
		return sum(x.get(field, 0) for (d, x) in self.history) / len(self.history)

	def total(self, field:str):
		"""
		# The total of the field according to the snapshot.
		"""
		return self.snapshot[field]

	def update(self, key, value, count=1):
		"""
		# Update the total and the current.
		"""
		self.current[key] += value
		self.snapshot[key] += value

	def changes(self):
		"""
		# Create iterator reporting the fields with changes in current.
		"""
		return self.current.keys()

	def commit(self, time):
		self.history.append((time, self.current))
		self.duration += time
		self.current = collections.defaultdict(int)

	def trim(self, window=8):
		"""
		# Remove history records that are past the &window.
		"""
		t = 0
		i = None
		data = None
		for (d, data), i in zip(reversed(self.history), range(len(self.history) - 1, -1, -1)):
			assert data is self.history[i][1]

			t += d
			if t > window:
				break
		else:
			# Nothing beyond window.
			return

		# Maintain some data for the time that is still within the window.
		time_removed = t - window
		time_remains = d - time_removed

		f = time_remains / d
		del self.history[:i]
		for k, v in data.items():
			data[k] *= f

		assert self.history[0][1] is data
		self.history[0] = (time_remains, data)

class Layout(object):
	"""
	# The set, sizes, and ordering of fields present in a monitor.
	"""

	# Identifier-width(cell count) pairs.
	Definition = typing.Tuple[str, int]
	Fields = typing.Sequence[Definition]

	@staticmethod
	def separators(fields:int, termination=".", separation=", "):
		"""
		# Generate a series of separators finished with a terminator.
		# Given a number of a fields, emit separators until the final index
		# is reached.
		"""

		for x in range(fields-1):
			yield separation

		yield termination

	def label(self, field, text:str):
		"""
		# The display text for the field's label.
		"""
		self.labels[field] = text

	def __init__(self, fields:Fields, **updates):
		self.labels = {}
		self.order = [x[0] for x in fields]
		self.cells = dict(fields)
		self.cells.update(updates.items())

	def fields(self):
		"""
		# Iterate over the fields in their designated order along with separators
		# that can be used to follow the rendered field.
		"""
		return zip(self.order, self.separators(len(self.order)))

class Theme(object):
	"""
	# The rendering methods and parameters used by a &Monitor.
	"""
	Formatter = typing.Tuple[str, str]

	def default_render_method(self, key, field):
		"""
		# Renders the string form of &field with the style set identified
		# by &key.
		"""
		return [
			('plain' if key not in self.stylesets else key, str(field)),
		]

	@staticmethod
	def r_transparent(value:typing.Sequence[Formatter]):
		"""
		# Render method expecting and returning a sequence of formatting pairs.

		# Used in cases where the field wishes to control theme-relative
		# formatting directly.
		"""
		return list(value)

	@staticmethod
	def r_duration(value):
		"""
		# Render method for common duration fields.
		"""
		time, precision = duration_repr(value)
		string = "{:.1f}".format(value)

		return [
			('duration', string),
			(precision+'-timeunit', precision),
		]

	def define(self, name, *args, using='plain', **kw):
		"""
		# Define a set of render parameters within the theme.
		# Parameters aside from &name are passed to &matrix.Context.RenderParameters.apply.
		"""
		self.stylesets[name] = self.stylesets[using].apply(*args, **kw)

	def implement(self, type, render):
		"""
		# Assign a render method, &call, for the &field.
		"""
		self.rendermethod[type] = render

	def __init__(self, default:matrix.Context.RenderParameters):
		from ..terminal import palette
		self.rendermethod = {}
		plain = default.apply()
		self.stylesets = {
			# Time is expected to be common among all themes.
			'plain': plain,
			'bold': plain.apply('bold'),
			's-timeunit': plain.apply(textcolor=palette.colors['blue']),
			'm-timeunit': plain.apply(textcolor=palette.colors['yellow']),
			'h-timeunit': plain.apply(textcolor=palette.colors['orange']),
			'd-timeunit': plain.apply(textcolor=palette.colors['red']),
			'Label': plain.apply(textcolor=palette.colors['foreground-adjacent']),
			'Label-Emphasis': plain.apply('bold', textcolor=palette.colors['foreground-adjacent']),
		}

	def style(self, celltexts:typing.Sequence[Formatter]):
		"""
		# Emit words formatted according to their associated style set for forming
		# a &matrix.Context.Phrase instance.
		"""
		idx = self.stylesets
		for style_idx, text in celltexts:
			yield idx[style_idx].form(text)

		yield idx['plain'].form('')

	def render(self, type, field, Phrase=matrix.Context.Phrase.from_words, partial=tools.partial):
		"""
		# Render the given &field according to the configured &type' render method.
		"""
		r_method = self.rendermethod.get(type) or partial(self.default_render_method, type)
		return Phrase(*self.style(r_method(field)))

class Monitor(object):
	"""
	# Allocated area for status display of a set of changing fields.

	# Structure holding the target &matrix.Context with the rendering
	# function and an associated state snapshot.
	"""

	view_state_loop = {
		'total': 'rate',
		'rate': 'overall',
		'overall': 'total',
	}

	def __init__(self, theme:Theme, layout:Layout, context:matrix.Context):
		self.theme = theme # Style sets and value rendering methods.
		self.context = context # fault.terminal drawing context.
		self.layout = layout # Field Ordering and Width
		self.metrics = Metrics() # Raw value sets and window.
		self.view = {} # Field view identifying value filtering (rate vs total).

		# Monitor local:
		self._title = None
		self._prefix = None
		self._suffix = None
		self._positions = list(self._calculate_fields())

		self._pcache = {}
		for (k, fpad), (position, cells, lc) in zip(layout.fields(), self._positions):
			self._pcache[k] = (fpad, position, cells, lc)

	def _calculate_fields(self, alignment=1):
		Phrase = self.context.Phrase
		position = 0

		fl = self.layout.labels
		cc = self.layout.cells
		for f in self.layout.order:
			cells = cc[f]
			label = self.theme.render('label-'+f, fl[f])
			lc = label.cellcount()
			usage = abs(cells) + lc + 2
			yield (position, cells, lc)

			indents, r = divmod(usage, alignment)
			position += (indents * alignment)
			if r != 0:
				position += alignment

		yield (position, 0, 0)

	def cycle(self, field):
		"""
		# Select a filter for reading the field.
		"""

		current = self.view.get(field, 'total')
		next = self.view_state_loop[current]
		self.view[field] = next

	def prefix(self, *words):
		"""
		# Attach a constant phrase to the beginning of the monitor.
		"""
		self._prefix = matrix.Context.Phrase.from_words(*words)

	def suffix(self, *words):
		"""
		# Attach a constant phrase to the end of the monitor.
		"""
		self._suffix = matrix.Context.Phrase.from_words(*words)

	def title(self, title, *dimensions):
		"""
		# Assign the monitor's title and dimension identifiers.
		"""
		self._title = (title, dimensions)

	def render(self, offset=58):
		render = self.theme.render
		layout = self.layout
		metrics = self.metrics

		label = render('Label', "duration")
		value = render('duration', metrics.duration)
		yield label, value, 40, 8 - value.cellcount()

		for (k, fpad), (position, cells, lc) in zip(layout.fields(), self._positions):
			readv = getattr(metrics, self.view.get(k, 'total'))
			try:
				value = render(k, readv(k))
			except ZeroDivisionError:
				value = render(k, metrics.total(k))

			lstr = layout.labels[k]
			ncells = value.cellcount()
			label = render('Label', lstr)

			yield label, value, position + offset, (cells - ncells)

	def delta(self, fields, offset=58):
		render = self.theme.render
		labels = self.layout.labels
		metrics = self.metrics

		label = render('Label', "duration")
		value = render('duration', metrics.duration)
		yield label, value, 40, 8 - value.cellcount()

		for k, (fpad, position, cells, lc) in ((k, self._pcache[k]) for k in fields):
			readv = getattr(metrics, self.view.get(k, 'total'))
			try:
				value = render(k, readv(k))
			except ZeroDivisionError:
				value = render(k, metrics.total(k))

			lstr = labels.get(k, k)
			ncells = value.cellcount()
			label = render('Label', lstr)

			yield label, value, position + offset, (cells - ncells)

	def phrase(self) -> matrix.Context.Phrase:
		"""
		# The monitor's image as a single phrase instance.
		"""
		phrases = list(self.render())
		labels = (x[0] for x in phrases)
		values = (x[1] for x in phrases)

		n = (lambda x: self.theme.render('Label', x))
		sep = (n(' '))
		lseps = (sep for i in range(len(phrases)))
		fseps = map(n, self.layout.separators(len(phrases)))

		return tools.interlace(values, lseps, labels, fseps)

	def snapshot(self, encoding='utf-8') -> bytes:
		"""
		# A bytes form of the &Monitor.phrase. (The image without cursor movement)
		"""
		l = list(self.phrase())
		cells = sum(x.cellcount() for x in l)
		rph = map(self.context.render, l)
		return cells, b''.join(itertools.chain.from_iterable(rph)).decode('utf-8')

class Control(object):
	"""
	# Root monitor control; manages the device interface, screen, and status context.
	"""

	def __init__(self, device, screen, context):
		self.device = device
		self.screen = screen
		self.context = context

		self._buffer = []
		self._io = io.FileIO(device.fileno(), closefd=False, mode='w')
		self._write = self._io.write

	def allocate(self, point, width=None, height=1) -> matrix.Context:
		"""
		# Create a &matrix.Context instance relative to the &Control' status context.
		"""
		rctx = self.context
		if width is None:
			width = rctx.width
		if height is None:
			height = rctx.height

		top, left = point
		actx = self.context.__class__(rctx.terminal_type)
		actx.context_set_position((rctx.point[0]+top, rctx.point[1]+left))
		actx.context_set_dimensions((width, height))
		return actx

	def frame(self, monitor, offset=0):
		"""
		# Render and emit the prefix, title, and suffix of the &monitor.

		# Operation is buffered and must be flushed to be displayed.
		"""
		context = monitor.context

		if monitor._prefix:
			offset = offset + monitor._prefix.cellcount() + 2

			i = itertools.chain.from_iterable([
				(context.seek((0, 0)),),
				context.render(monitor._prefix),
			])
			self._buffer.append(b''.join(i))
			self._buffer.append(monitor.context.reset_text())

		ph = monitor.theme.render('title', monitor._title)
		i = itertools.chain.from_iterable([
			(context.seek((offset, 0)),),
			context.render(ph),
			(b':',),
		])
		self._buffer.append(b''.join(i))

		self._buffer.append(monitor.context.reset_text())

		if monitor._suffix:
			i = itertools.chain.from_iterable([
				context.render(monitor._suffix),
			])
			self._buffer.append(b''.join(i))
			self._buffer.append(monitor.context.reset_text())

	def update(self, monitor, fields, offset=0):
		"""
		# Render and emit the given &fields.

		# Operation is buffered and must be flushed to be displayed.
		"""
		context = monitor.context

		for label, ph, position, pad in fields:
			i = itertools.chain.from_iterable([
				(context.seek((position+offset, 0)), b' ' * pad),
				context.render(ph),
				(b' ',),
				context.render(label) if label else (),
			])
			self._buffer.append(b''.join(i))

		self._buffer.append(context.reset_text())

	def flush(self):
		"""
		# Write any buffered terminal changes to the device.
		"""
		l = len(self._buffer)
		buf = bytearray()
		buf += self.screen.exit_scrolling_region()
		for x in itertools.islice(self._buffer, 0, l):
			buf += x
		buf += self.screen.enter_scrolling_region()

		try:
			self._write(buf)
		except:
			raise
		else:
			del self._buffer[:l]

	def clear(self, monitor):
		"""
		# Clear the area used by the monitor's context.

		# Operation is buffered and must flushed to be effective.
		"""
		self._buffer.append(monitor.context.clear())

def setup(lines:int, atexit=b'', type='prepared',
		destruct=True,
		Context=matrix.Context,
	) -> Control:
	"""
	# Initialize the terminal for use with a scrolling region.

	# The given &lines determines the horizontal area allocation to
	# manage at the bottom or top of the screen. If negative,
	# the top of the screen will be allocated. Allocating both is
	# not supported by this interface as &Control only manages one
	# &matrix.Context.
	"""
	if not lines:
		raise ValueError("line allocation must be non-zero")

	from ..terminal import control
	screen = matrix.Screen()

	device = control.setup(type,
		atexit=screen.close_scrolling_region()+atexit,
		destruct=destruct,
	)

	hv = device.get_window_dimensions()
	screen.context_set_dimensions(hv)

	ctx = Context(screen.terminal_type)
	if lines > 0:
		t = 0
		v = hv[1] - lines

		ctx.context_set_position((0, v))
		ctx.context_set_dimensions((hv[0], lines))
		init = (b'\n' * lines) + screen.seek_vertical_relative(-lines)
	else:
		# Allocate top.
		t = -lines
		v = hv[1]

		ctx.context_set_position((0, 0))
		ctx.context_set_dimensions((hv[0], -lines))
		init = screen.store_cursor_location() + ctx.clear() + screen.restore_cursor_location()

	init += screen.open_scrolling_region(t, v-1)
	ctl = Control(device, screen, ctx)
	ctl._write(init)
	return ctl

if __name__ == '__main__':
	import time
	st_ctl = setup(1, width=80)
	st_ctl.initialize(['field-1', 'field-2'])
	st_ctl.update({'field-1': 0, 'field-2': 'test'})
	print('test-1')
	time.sleep(1)
	st_ctl.update({'field-1': 6, 'field-2': 'test-2'})
	print('test-2')
	time.sleep(2)
