from uuid import uuid4

import six

from urllib3.pipeline.context import Context, ContextWrapper

def has_callable_attr(obj, attr_name):
    return hasattr(obj, attr_name) and hasattr(getattr(obj, attr_name), '__call__')


class HttpPipelineElement(object):
    
    def __init__(self):
        """
        Each instance of HttpPipelineElement should have a unique identifier
        that can be used to store state in a context object.
        """
        self.id = uuid4().hex

    def save_context(self, context, key, value):

        context.setdefault(self.id, {})
        context[self.id][key] = value

    def get_context(self, context, key, default=None):
        return context.get(self.id, {}).get(key, default)

    def apply(self, context, **kwargs):
        return kwargs

    def resolve(self, context, response):
        return response

    def _apply(self, context, **kwargs):
        unique_context = ContextWrapper(self.id, context)
        return self.apply(unique_context, **kwargs)

    def _resolve(self, context, response):
        unique_context = ContextWrapper(self.id, context)
        return self.resolve(unique_context, response)


class PipelineDirections(object):
    forward = 1
    reverse = -1 


class ReverseResponse(object):

    def __init__(self, value):
        self.value = value


class HttpPipeline(HttpPipelineElement):

    def __init__(self, *args):
        if not all(isinstance(each, HttpPipelineElement) for each in args):
            raise TypeError(
                'All elements passed to HttpPipeline must be '
                'subclasses of HttpPipelineElement'
            )
        self._steps = args
        super(HttpPipeline, self).__init__()

    def steps(self, start_at=None, direction=PipelineDirections.forward):
        start_yielding = False
        for each in self._steps[::direction]:
            if start_yielding or start_at is None:
                yield each
            if start_at is not None and each.id == start_at:
                start_yielding = True

    def _apply(self, context, **kwargs):
        return self.apply(context, **kwargs)

    def _resolve(self, context, response):
        return self.resolve(context, response)

    def apply(self, context, start_at=None, **kwargs):
        element_id = None
        try:
            for element in self.steps(start_at=start_at, direction=PipelineDirections.forward):
                element_id = element.id
                next_val = element._apply(context, **kwargs)
                if next_val is not None:
                    kwargs = next_val
                if isinstance(kwargs, ReverseResponse):
                    return self.resolve(context, kwargs.value, start_at=element_id)
            return kwargs
        except Exception as e:
            return self._handle_exception(context, e, location=element_id)

    def resolve(self, context, response, start_at=None):
        element_id = None
        try:
            for element in self.steps(start_at=start_at, direction=PipelineDirections.reverse):
                element_id = element.id
                next_val = element._resolve(context, response)
                if next_val is not None:
                    response = next_val
                if isinstance(response, ReverseResponse):
                    return self.apply(context, start_at=element_id, **response.value)
            return response
        except Exception as e:
            return self._handle_exception(context, e, location=element_id)

    def _handle_exception(self, context, error, location=None):
        for element in self.steps(start_at=location, direction=PipelineDirections.reverse):
            try:
                if hasattr(element, 'handle_exception'):
                    direction, data = element.handle_exception(context, error)
                else:
                    raise error
                if direction == PipelineDirections.forward:
                    return self.apply(context, start_at=location, **data)
                elif direction == PipelineDirections.reverse:
                    return self.resolve(context, data, start_at=location)
            except Exception as e:
                error = e
        raise error

    def handle_exception(self, context, error):
        return self._handle_exception(context, error)

    def request(self, **kwargs):
        context = Context()
        response = self.apply(context, **kwargs)
        return self.resolve(context, response)


class DefinedPipeline(HttpPipeline):

    elements = []

    def __init__(self):
        steps = []
        for each in self.elements:
            steps.append(self._initialize_element(each))
        super(DefinedPipeline, self).__init__(*steps)

    def _initialize_element(self, element):
        if isinstance(element, HttpPipelineElement):
            return element
        else:
            return element()
