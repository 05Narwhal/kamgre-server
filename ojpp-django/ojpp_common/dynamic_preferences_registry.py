from ckeditor.widgets import CKEditorWidget
from dynamic_preferences.preferences import Section
from dynamic_preferences.registries import global_preferences_registry
from dynamic_preferences.types import StringPreference

general = Section('frontend')


@global_preferences_registry.register
class AnnouncementType(StringPreference):
    section = general
    name = 'announcement_type'
    default = ''
    required = False


@global_preferences_registry.register
class AnnouncementText(StringPreference):
    section = general
    name = 'announcement_text'
    widget = CKEditorWidget
    default = ''
    required = False
