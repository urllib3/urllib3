class ContextWrapper(object):

    def __init__(self, pipeline_element_id, context):
        self.element_id = pipeline_element_id
        self.context = context

    def save(self, key, value):
        self.context._save(self.element_id, key, value)

    def get(self, key, default=None):
        return self.context._get(self.element_id, key, default)

    def pop(self, key, default=None):
        return self.context._pop(self.element_id, key, default)

class Context(dict):

    def _save(self, pipeline_element_id, key, value):
        self.setdefault(pipeline_element_id, {})
        self[pipeline_element_id][key] = value

    def _get(self, pipeline_element_id, key, default=None):
        if pipeline_element_id in self:
            return self[pipeline_element_id].get(key, default)
        else:
            return default

    def _pop(self, pipeline_element_id, key, default=None):
        if pipeline_element_id in self:
            return self[pipeline_element_id].pop(key, default)
        else:
            return default