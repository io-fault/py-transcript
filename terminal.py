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
from ..status import frames

def duration_repr(seconds) -> typing.Tuple[float, str]:
	if seconds < 90:
		# seconds, minute and a half
		return (seconds / 1.0, 's')

	minutes = seconds / 60
	if minutes < 90:
		# minutes, hour and a half
		return (seconds / 60, 'm')

	hours = minutes / 60
	if hours < 240:
		return (hours, 'h')

	days = hours / 24
	return (days, 'd')

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
		self.paths = [tuple(x[1].split('.')) for x in fields]
		self.cells = {x[0]: x[2] for x in fields}
		self.cells.update(updates.items())

	def fields(self):
		"""
		# Iterate over the fields in their designated order along with separators
		# that can be used to follow the rendered field.
		"""
		return zip(self.order, self.paths, self.separators(len(self.order)))

	def positions(self):
		"""
		# Join the field identifier, cell allocation, and field label in
		# the order designated by &order.
		"""
		fl = self.labels
		cc = self.cells

		for fid in self.order:
			yield (fid, fl[fid], cc[fid])

class Theme(object):
	"""
	# The rendering methods and parameters used by a &Status.
	"""
	from ..terminal import palette

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
		self.rendertraits = default
		self.stylesets = {}
		self.rendermethod = {}

	def configure(self, colors):
		plain = self.rendertraits.apply()
		rctl = plain.apply
		self.stylesets.update({
			# Time is expected to be common among all themes.
			'plain': plain,
			'bold': rctl('bold'),
			's-timeunit': rctl(textcolor=colors['blue']),
			'm-timeunit': rctl(textcolor=colors['yellow']),
			'h-timeunit': rctl(textcolor=colors['orange']),
			'd-timeunit': rctl(textcolor=colors['red']),
			'Label': rctl(textcolor=colors['foreground-adjacent']),
			'Label-Emphasis': rctl('bold', textcolor=colors['foreground-adjacent']),
		})
		return self

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

class Status(object):
	"""
	# Allocated area for status display of a set of changing fields.

	# Structure holding the target &matrix.Context with the rendering
	# function and an associated state snapshot.
	"""

	view_state_loop = {
		'total': 'rate_window',
		'rate_window': 'rate_overall',
		'rate_overall': 'total',
	}

	unit_type_separators = {
		'total': '+',
		'rate_window': '<',
		'rate_overall': '^',
	}

	def __init__(self, theme:Theme, layout:Layout, context:matrix.Context):
		self.theme = theme # Style sets and value rendering methods.
		self.layout = layout # Field Ordering and Width
		self.context = context # fault.terminal drawing context.
		self.metrics = None
		self.view = {} # Field view identifying value filtering (rate vs total).

		# Status local:
		self._title = None
		self._prefix = None
		self._suffix = None
		self._update_field_cache()

	def _calculate_fields(self, alignment=1):
		position = 0
		trender = self.theme.render

		for fid, flabel, cells in self.layout.positions():
			rlabel = trender('label-'+fid, flabel)
			lc = rlabel.cellcount()
			usage = abs(cells) + lc + 2
			yield (position, cells, lc)

			indents, r = divmod(usage, alignment)
			position += (indents * alignment)
			if r != 0:
				position += alignment

		yield (position, 0, 0)

	def _update_field_cache(self):
		self._positions = list(self._calculate_fields())
		self._pcache = {
			k: (path, fpad, position, cells, lc)
			for (k, path, fpad), (position, cells, lc) in zip(self.layout.fields(), self._positions)
		}

	def reset(self, time, metrics):
		"""
		# Reset the metrics records using the given entry as the only one.
		"""
		self.metrics = [(time, metrics)]

	@property
	def current(self):
		return self.metrics[-1][1]

	def elapse(self, time):
		"""
		# Update the time field on the last metrics record.
		"""
		cur = self.metrics[-1][0]
		if cur == time:
			return
		self.metrics[-1] = (time, self.metrics[-1][1])

	def update(self, time, metrics, window=8*(10**9)):
		"""
		# Update the metrics record for the given point in time.
		"""
		self.metrics.append((time, metrics))

		cutoff = time - window
		for i, x in enumerate(self.metrics, 1):
			if x[0] > cutoff:
				del self.metrics[1:i]
				break

	def duration(self):
		return (self.metrics[-1][0] - self.metrics[0][0])

	def cycle(self, field):
		"""
		# Select the next read type for the given field using the &view_state_loop.
		"""

		units = self.view.get(field, 'total')
		next = self.view_state_loop[units]
		self.view[field] = next

	def set_field_read_type(self, field, units):
		if units not in self.view_state_loop:
			raise ValueError(units)
		self.view[field] = units

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

	def window_period(self):
		"""
		# Calculate the current metrics window size.
		"""
		try:
			start = self.metrics[1][0]
		except IndexError:
			start = self.metrics[0][0]

		return self.metrics[-1][0] - start

	def origin(self, field):
		return self.metrics[0][1][field]

	def window_delta(self, field):
		if len(self.metrics) <= i:
			i=0

		start = self.metrics[i][1][field]
		stop = self.metrics[-1][1][field]
		return stop - start

	def edge(self, field, i=1):
		if len(self.metrics) <= i:
			i=0
		return self.metrics[i][1][field]

	def total(self, field):
		return self.metrics[-1][1][field]

	def rate_window(self, field):
		delta = self.total(field) - self.edge(field)
		return delta / self.window_period()

	def rate_overall(self, field):
		delta = self.total(field) - self.edge(field)
		return delta / self.duration()

	def render(self, filter=(lambda x: False), offset=58):
		render = self.theme.render
		layout = self.layout
		metrics = self.metrics

		label = render('Label', "duration")
		value = render('duration', self.duration() / (10**9))
		yield 'total', label, value, 40, 8 - value.cellcount()

		for (k, path, fpad), (position, cells, lc) in zip(layout.fields(), self._positions):
			utype = self.view.get(k, 'total')
			readv = getattr(self, utype)
			try:
				v = readv(path)
			except ZeroDivisionError:
				utype = 'total'
				v = self.total(path)

			if filter(v):
				continue
			value = render(k, v)

			lstr = layout.labels[k]
			ncells = value.cellcount()
			label = render('Label', lstr)

			yield utype, label, value, position + offset, (cells - ncells)

	def delta(self, fields, offset=58):
		render = self.theme.render
		labels = self.layout.labels
		metrics = self.metrics

		label = render('Label', "duration")
		value = render('duration', self.duration() / (10**9))
		yield 'total', label, value, 40, 8 - value.cellcount()

		fields = ((k, self._pcache[k]) for k in fields if k in self._pcache)
		for k, (path, fpad, position, cells, lc) in fields:
			utype = self.view.get(k, 'total')
			readv = getattr(self, utype)
			try:
				v = readv(path)
			except ZeroDivisionError:
				utype = 'total'
				v = self.total(path)

			value = render(k, v)
			lstr = labels.get(k, k)
			ncells = value.cellcount()
			label = render('Label', lstr)

			yield utype, label, value, position + offset, (cells - ncells)

	def phrase(self, filter=(lambda x: False)) -> matrix.Context.Phrase:
		"""
		# The monitor's image as a single phrase instance.
		"""
		phrases = list(self.render(filter=filter))
		utypes = (x[0] for x in phrases)
		labels = (x[1] for x in phrases)
		values = (x[2] for x in phrases)

		n = (lambda x: self.theme.render('Label-Separator', x))
		lseps = (n(self.unit_type_separators[x]) for x in utypes)
		fseps = map(n, self.layout.separators(len(phrases)))

		return tools.interlace(values, lseps, labels, fseps)

	def snapshot(self, encoding='utf-8') -> bytes:
		"""
		# A bytes form of the &Status.phrase. (The image without cursor movement)
		"""
		l = list(self.phrase(filter=(lambda x: x in {0,0.0,"0"})))
		cells = sum(x.cellcount() for x in l)
		rph = map(self.context.render, l)
		return cells, b''.join(itertools.chain.from_iterable(rph)).decode('utf-8')

	def profile(self):
		"""
		# Construct a triple containing the start and stop time and the final metrics.
		"""
		return (self.metrics[0][0], self.metrics[-1][0], self.metrics[-1][1])

	def synopsis(self, context=None, vmap={'rate_window':'rate_overall'}):
		"""
		# Construct a status frame synopsis using the monitor's configuration and metrics.
		"""
		sv = dict(self.view)
		try:
			for k, v in list(self.view.items()):
				self.view[k] = vmap.get(v, v)

			cells, mss = self.snapshot()

			if context is None:
				ctx = self._title[0] + ': '
			elif context:
				ctx = context + ': '
			else:
				ctx = ''

			return ctx + mss + self.context.reset_text().decode('utf-8')
		finally:
			self.view = sv

	def frame(self, type, identifier, channel=None):
		"""
		# Construct a transaction frame for reporting the status.
		# Used after the completion of the dispatcher.
		"""
		start, stop, metrics = self.profile()
		ext = {
			'@timestamp': [str(start)],
			'@duration': [str(stop - start)],
			'@metrics': [metrics.sequence()],
		}
		if identifier:
			ext['@transaction'] = [identifier]

		return frames.compose(type, self.synopsis(identifier), channel, ext)

class Monitor(object):
	"""
	# Terminal display management for monitoring changes in &Status instances.
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
		# Create a &matrix.Context instance relative to the &Monitor' status context.
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

	def install(self, monitor):
		"""
		# Erase, reframe, and update the given monitor..
		"""
		self.erase(monitor)
		self.frame(monitor)
		self.update(monitor, monitor.render())

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
		R = monitor.theme.render
		chain = itertools.chain.from_iterable

		for utype, label, ph, position, pad in fields:
			lsep = R('Label-Separator', monitor.unit_type_separators[utype])
			i = chain([
				(context.seek((position+offset, 0)), b' ' * pad),
				context.render(ph),
				context.render(lsep),
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
		buf += self.screen.set_cursor_visible(False)
		for x in itertools.islice(self._buffer, 0, l):
			buf += x
		buf += self.screen.enter_scrolling_region()
		buf += self.screen.set_cursor_visible(True)

		try:
			self._write(buf)
		except:
			raise
		else:
			del self._buffer[:l]

	def erase(self, monitor):
		"""
		# Clear the area used by the monitor's context.

		# Operation is buffered and must flushed to be effective.
		"""
		self._buffer.append(monitor.context.clear())

	def clear(self):
		"""
		# Clear the entire configured area for status.
		# Used when transitioning monitor configurations.
		"""
		self._buffer.append(self.context.clear())

	def configure(self, lines:int):
		"""
		# Configure the scrolling region allocating &lines at
		# the top or bottom of the screen for status display.

		# This method should be called after window changes of any type.
		# The window size is refreshed from the device; monitors should
		# also be reallocated so that their Context positions can be adjusted.
		"""
		if not lines:
			raise ValueError("line allocation must be non-zero")

		ctx = self.context
		scr = self.screen
		hv = self.device.get_window_dimensions()
		scr.context_set_dimensions(hv)

		if lines > 0:
			t = 0
			v = hv[1] - lines

			ctx.context_set_position((0, v))
			ctx.context_set_dimensions((hv[0], lines))
			init = (b'\n' * lines) + scr.seek_vertical_relative(-lines)
		else:
			# Allocate top.
			t = -lines
			v = hv[1]

			ctx.context_set_position((0, 0))
			ctx.context_set_dimensions((hv[0], -lines))
			init = scr.store_cursor_location() + ctx.clear() + scr.restore_cursor_location()

		init += scr.open_scrolling_region(t, v-1)
		self._write(init)
		return self

def setup(atrestore=b'', type='prepared',
		destruct=True,
		Context=matrix.Context,
	) -> Monitor:
	"""
	# Initialize the terminal for use with a scrolling region.

	# The given &lines determines the horizontal area allocation to
	# manage at the bottom or top of the screen. If negative,
	# the top of the screen will be allocated. Allocating both is
	# not supported by this interface as &Monitor only manages one
	# &matrix.Context.
	"""
	import atexit
	from ..terminal import control
	screen = matrix.Screen()

	device, tty_prep, tty_rest = control.setup(type,
		atrestore=screen.close_scrolling_region()+atrestore,
		destruct=destruct,
	)
	tty_prep()
	atexit.register(tty_rest)

	return Monitor(device, screen, Context(screen.terminal_type))

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

def r_count(field, value, isinstance=isinstance):
	"""
	# Render method for counts providing compression using metric units.
	"""

	if isinstance(value, str) or (value < 100000 and not isinstance(value, float)):
		n = str(value)
		unit = ''
	else:
		n, unit = _strings(value)

	if n == "0":
		# By default, don't color zeros.
		field = 'plain'

	return [
		(field, n),
		('unit-label', unit)
	]

def r_title(value):
	"""
	# Render method for monitor titles.
	"""
	category, dimensions = value
	t = str(category)
	if dimensions:
		t += '[' + ']['.join(dimensions) + ']'
	return [('plain', t)]

def form(module, colors=Theme.palette.colors):
	"""
	# Construct a &Layout and &Theme from the provided order and formatting structures.
	"""
	l = Layout(module.order)
	t = Theme(matrix.Type.normal_render_parameters).configure(colors)
	t.implement('duration', Theme.r_duration)
	t.implement('title', r_title)

	t.define('Label-Separator', textcolor=colors['background-adjacent'])
	t.define('duration', textcolor=colors['white'])
	t.define('unit-label', textcolor=colors['gray'])
	t.define('data-rate-receive', textcolor=colors['terminal-default'])
	t.define('data-rate-transmit', textcolor=colors['terminal-default'])
	t.define('data-rate', textcolor=colors['gray'])

	for (k, path, width), (keycode, label, color, fn) in zip(module.order, module.formats):
		if fn is not None:
			t.implement(k, fn)
		t.define(k, textcolor=colors[color])
		l.label(k, label or None)

	return t, l, getattr(module, 'types', {})

def aggregate(control:Monitor, module, lanes=1, width=80):
	"""
	# Construct &Status instances allocated using &control for
	# displaying the aggregate of the dimension allocations.

	# Returns a sequence of &Status instances for the dimensions
	# and a single Status for the aggregation.
	"""
	t, l, types = form(module)
	lanes_seq = [
		Status(t, l, control.allocate((0, i), width=width))
		for i in range(lanes)
	]
	m = Status(t, l, control.allocate((0, lanes), width=width))

	for k, v in types.items():
		m.set_field_read_type(k, v)
		for x in lanes_seq:
			x.set_field_read_type(k, v)

	return lanes_seq, m
