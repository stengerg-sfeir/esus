"""Generic pyimgui CRUD GUI: one window per modeled entity.

Generation principle: the PANELS table below is built from the
documents — one panel per entity that has repository CRUD methods
— and the rest of this file is a fixed runtime that draws every
panel the same way. No bespoke screens: the documents describe
no forms or events, so every entity gets the same working
surface — record list, field inputs with Add/Update, delete by
id — wired to the mechanical CRUD methods only. Service methods
without one stay out; their stubs refuse with their work order.

Requires: pip install imgui glfw PyOpenGL
"""

from __future__ import annotations

import imgui
import glfw
from imgui.integrations.glfw import GlfwRenderer
from OpenGL import GL as gl

import sys

import models
import errors
from schema import SCHEMA
from store import Store
import repositories


DEFAULT_DB = 'prompt_gui.db'


PANELS = [{'entity': 'Wine', 'model': 'Wine', 'repo': 'WineRepository', 'pk': 'id', 'fields': [{'name': 'id', 'kind': 'int', 'pk': True}, {'name': 'name', 'kind': 'str', 'pk': False}, {'name': 'vintage_year', 'kind': 'int', 'pk': False}, {'name': 'wine_type', 'kind': 'str', 'pk': False}, {'name': 'country_of_origin', 'kind': 'str', 'pk': False}, {'name': 'cost_price', 'kind': 'float', 'pk': False}, {'name': 'selling_price', 'kind': 'float', 'pk': False}, {'name': 'stock_quantity', 'kind': 'int', 'pk': False}, {'name': 'storage_location_id', 'kind': 'int', 'pk': False}], 'ops': {'read_all': {'method': 'read_all', 'specs': [{'raw': 'name', 'py': 'name', 'kind': 'str', 'entity': False}, {'raw': 'vintage_year', 'py': 'vintage_year', 'kind': 'int', 'entity': False}, {'raw': 'wine_type', 'py': 'wine_type', 'kind': 'str', 'entity': False}, {'raw': 'country_of_origin', 'py': 'country_of_origin', 'kind': 'str', 'entity': False}, {'raw': 'cost_price', 'py': 'cost_price', 'kind': 'int', 'entity': False}, {'raw': 'selling_price', 'py': 'selling_price', 'kind': 'int', 'entity': False}, {'raw': 'stock_quantity', 'py': 'stock_quantity', 'kind': 'int', 'entity': False}, {'raw': 'storage_location_id', 'py': 'storage_location_id', 'kind': 'int', 'entity': False}]}, 'read_one': {'method': 'read_one', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}]}, 'create': {'method': 'create', 'specs': [{'raw': 'name', 'py': 'name', 'kind': 'str', 'entity': False}, {'raw': 'vintage_year', 'py': 'vintage_year', 'kind': 'int', 'entity': False}, {'raw': 'wine_type', 'py': 'wine_type', 'kind': 'str', 'entity': False}, {'raw': 'country_of_origin', 'py': 'country_of_origin', 'kind': 'str', 'entity': False}, {'raw': 'cost_price', 'py': 'cost_price', 'kind': 'int', 'entity': False}, {'raw': 'selling_price', 'py': 'selling_price', 'kind': 'int', 'entity': False}, {'raw': 'stock_quantity', 'py': 'stock_quantity', 'kind': 'int', 'entity': False}, {'raw': 'storage_location_id', 'py': 'storage_location_id', 'kind': 'int', 'entity': False}]}, 'update': {'method': 'update', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}, {'raw': 'name', 'py': 'name', 'kind': 'str', 'entity': False}, {'raw': 'vintage_year', 'py': 'vintage_year', 'kind': 'int', 'entity': False}, {'raw': 'wine_type', 'py': 'wine_type', 'kind': 'str', 'entity': False}, {'raw': 'country_of_origin', 'py': 'country_of_origin', 'kind': 'str', 'entity': False}, {'raw': 'cost_price', 'py': 'cost_price', 'kind': 'int', 'entity': False}, {'raw': 'selling_price', 'py': 'selling_price', 'kind': 'int', 'entity': False}, {'raw': 'stock_quantity', 'py': 'stock_quantity', 'kind': 'int', 'entity': False}, {'raw': 'storage_location_id', 'py': 'storage_location_id', 'kind': 'int', 'entity': False}]}, 'delete': {'method': 'delete', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}, {'raw': 'name', 'py': 'name', 'kind': 'str', 'entity': False}, {'raw': 'vintage_year', 'py': 'vintage_year', 'kind': 'int', 'entity': False}, {'raw': 'wine_type', 'py': 'wine_type', 'kind': 'str', 'entity': False}, {'raw': 'country_of_origin', 'py': 'country_of_origin', 'kind': 'str', 'entity': False}, {'raw': 'cost_price', 'py': 'cost_price', 'kind': 'int', 'entity': False}, {'raw': 'selling_price', 'py': 'selling_price', 'kind': 'int', 'entity': False}, {'raw': 'stock_quantity', 'py': 'stock_quantity', 'kind': 'int', 'entity': False}, {'raw': 'storage_location_id', 'py': 'storage_location_id', 'kind': 'int', 'entity': False}]}}}, {'entity': 'StorageLocation', 'model': 'StorageLocation', 'repo': 'StorageLocationRepository', 'pk': 'id', 'fields': [{'name': 'id', 'kind': 'int', 'pk': True}, {'name': 'zone_name', 'kind': 'str', 'pk': False}, {'name': 'row_number', 'kind': 'int', 'pk': False}, {'name': 'shelf_number', 'kind': 'int', 'pk': False}, {'name': 'maximum_capacity', 'kind': 'int', 'pk': False}], 'ops': {'read_all': {'method': 'read_all', 'specs': [{'raw': 'zone_name', 'py': 'zone_name', 'kind': 'str', 'entity': False}, {'raw': 'row_number', 'py': 'row_number', 'kind': 'int', 'entity': False}, {'raw': 'shelf_number', 'py': 'shelf_number', 'kind': 'int', 'entity': False}, {'raw': 'maximum_capacity', 'py': 'maximum_capacity', 'kind': 'int', 'entity': False}]}, 'read_one': {'method': 'read_one', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}]}, 'create': {'method': 'create', 'specs': [{'raw': 'zone_name', 'py': 'zone_name', 'kind': 'str', 'entity': False}, {'raw': 'row_number', 'py': 'row_number', 'kind': 'int', 'entity': False}, {'raw': 'shelf_number', 'py': 'shelf_number', 'kind': 'int', 'entity': False}, {'raw': 'maximum_capacity', 'py': 'maximum_capacity', 'kind': 'int', 'entity': False}]}, 'update': {'method': 'update', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}, {'raw': 'zone_name', 'py': 'zone_name', 'kind': 'str', 'entity': False}, {'raw': 'row_number', 'py': 'row_number', 'kind': 'int', 'entity': False}, {'raw': 'shelf_number', 'py': 'shelf_number', 'kind': 'int', 'entity': False}, {'raw': 'maximum_capacity', 'py': 'maximum_capacity', 'kind': 'int', 'entity': False}]}, 'delete': {'method': 'delete', 'specs': [{'raw': 'id', 'py': 'id', 'kind': 'int', 'entity': False}, {'raw': 'zone_name', 'py': 'zone_name', 'kind': 'str', 'entity': False}, {'raw': 'row_number', 'py': 'row_number', 'kind': 'int', 'entity': False}, {'raw': 'shelf_number', 'py': 'shelf_number', 'kind': 'int', 'entity': False}, {'raw': 'maximum_capacity', 'py': 'maximum_capacity', 'kind': 'int', 'entity': False}]}}}]


TOOLBAR_WIDTH = 160


def _display():
    """The current display size (toolbar math needs it twice)."""
    return imgui.get_io().display_size


def _parse(kind, text):
    if text is None or (isinstance(text, str) and not text.strip()):
        return None
    if kind == "int":
        return int(str(text).strip())
    if kind == "float":
        return float(str(text).strip())
    if kind == "bool":
        return str(text).strip().lower() in ('1', 'true', 'yes', 'y')
    return str(text)


def _new_state():
    return {"rows": [], "inputs": {}, "id": "", "message": "", "open": True}


def _refresh(panel, repo, state):
    op = panel["ops"].get("read_all")
    if op is None:
        state["message"] = "no list method"
        return
    try:
        state["rows"] = getattr(repo, op["method"])()
        state["message"] = ""
    except Exception as error:
        state["message"] = f"error: {error}"


def _collect(panel, state, specs):
    """Split widgets into `(model_kwargs, scalar_kwargs)` for one call."""
    names = {f['name'] for f in panel['fields']}
    model_kwargs, scalar_kwargs = {}, {}
    for spec in specs:
        if spec['entity']:
            continue  # assembled into the model instance below
        if spec['raw'] in names:
            text = state['inputs'].get(spec['raw'], '')
            if not str(text).strip() and spec['raw'] == panel['pk']:
                text = state['id']  # pk has no widget; the id box serves it
        else:
            text = state['inputs'].get(spec['raw'], '')
        scalar_kwargs[spec['py']] = _parse(spec['kind'], text)
    for field in panel['fields']:
        value = _parse(field['kind'], state['inputs'].get(field['name'], ''))
        if value is not None:
            model_kwargs[field['name']] = value
    return model_kwargs, scalar_kwargs


def _invoke(panel, repo, state, op_name):
    op = panel["ops"].get(op_name)
    if op is None:
        state["message"] = f"no {op_name} method"
        return
    try:
        model_kwargs, scalar_kwargs = _collect(panel, state, op['specs'])
        call_kwargs = dict(scalar_kwargs)
        for spec in op['specs']:
            if spec['entity']:
                model_cls = getattr(models, panel['model'])
                call_kwargs[spec['py']] = model_cls(**model_kwargs)
        method = getattr(repo, op['method'])
        method(**call_kwargs)
        _refresh(panel, repo, state)  # add/update/delete reload the list
        if not state["message"]:
            state["message"] = f"{op_name} ok"
    except Exception as error:
        state["message"] = f"error: {error}"


def _draw_toolbar(states):
    """Left vertical bar, always visible: one button per window."""
    size = _display()
    imgui.set_next_window_position(0, 0)
    imgui.set_next_window_size(TOOLBAR_WIDTH, size.y)
    imgui.begin("toolbar")
    for panel in PANELS:
        state = states[panel['entity']]
        label = ('[x] ' if state['open'] else '[ ] ') + panel['entity']
        if imgui.button(label):
            state['open'] = not state['open']
    imgui.end()


def _draw_panel(panel, repo, state):
    size = _display()  # maximized in the space right of the toolbar
    imgui.set_next_window_position(TOOLBAR_WIDTH, 0)
    imgui.set_next_window_size(size.x - TOOLBAR_WIDTH, size.y)
    opened, _ = imgui.begin(panel['entity'], True)
    if not opened:
        imgui.end()
        return
    if state["message"]:
        imgui.text(state["message"])
    imgui.text(f"{panel['entity']} records:")
    columns = [f['name'] for f in panel['fields']] or ['-']
    if imgui.begin_table('rows', len(columns)):
        for name in columns:
            imgui.table_next_column()
            imgui.text(name)
        for row in state['rows']:
            imgui.table_next_row()
            record = row if isinstance(row, dict) else vars(row)
            for name in columns:
                imgui.table_next_column()
                imgui.text(str(record.get(name, '')))
        imgui.end_table()
    imgui.separator()
    for field in panel['fields']:
        if field['pk'] and 'create' in panel['ops']:
            continue  # assigned by the store on insert
        changed, value = imgui.input_text(
            field['name'], state['inputs'].get(field['name'], ''), 256)
        if changed:
            state['inputs'][field['name']] = value
    for op_name, label in (('create', 'Add'), ('update', 'Update')):
        if op_name in panel['ops']:
            imgui.same_line()
            if imgui.button(f"{label} {panel['entity']}"):
                _invoke(panel, repo, state, op_name)
    imgui.separator()
    _, state['id'] = imgui.input_text('id', state['id'], 64)
    imgui.same_line()
    if imgui.button('Delete') and 'delete' in panel['ops']:
        _invoke(panel, repo, state, 'delete')
    imgui.end()


def build_gui():
    store = Store(DEFAULT_DB, SCHEMA)
    repos = {}
    states = {}
    for panel in PANELS:
        repo = getattr(repositories, panel['repo'])(store)
        repos[panel['repo']] = repo
        state = _new_state()
        _refresh(panel, repo, state)
        states[panel['entity']] = state
    return repos, states


def main():
    if not PANELS:
        print("no GUI panels: no entity has CRUD methods")
        return 1
    if not glfw.init():
        print("could not initialize glfw")
        return 1
    # macOS defaults to a legacy GL context, which the stock
    # renderer cannot use (GLError 1282 in _create_device_objects).
    # Other platforms keep their default context: forcing a
    # profile there could break drivers that work fine as-is.
    if sys.platform == "darwin":
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    window = glfw.create_window(1280, 800, "crud", None, None)
    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)
    repos, states = build_gui()
    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        _draw_toolbar(states)
        for panel in PANELS:
            state = states[panel['entity']]
            if state['open']:
                _draw_panel(panel, repos[panel['repo']], state)
        gl.glClearColor(0.1, 0.1, 0.1, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
    impl.shutdown()
    glfw.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

