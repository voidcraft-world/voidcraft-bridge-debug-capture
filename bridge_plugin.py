from voidcraft_bridge_debug_capture.plugin import DebugCapturePlugin

PLUGIN_NAME = "debug-capture"


def create_plugin(context):
    return DebugCapturePlugin(context)
