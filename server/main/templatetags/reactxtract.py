from django import template


register = template.Library()


@register.filter
def lines(values):
    return '\n'.join(str(value) for value in (values or []))


@register.filter
def duration_ms(value):
    seconds = (value or 0) / 1000
    if seconds < 60:
        return f'{seconds:.1f}s'
    minutes, remainder = divmod(seconds, 60)
    return f'{int(minutes)}m {remainder:.0f}s'


@register.filter
def confidence_percent(value):
    try:
        return round(float(value) * 100)
    except (TypeError, ValueError):
        return 0


@register.filter
def confidence_class(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0
    if score >= 0.85:
        return 'high'
    if score >= 0.6:
        return 'medium'
    return 'low'

