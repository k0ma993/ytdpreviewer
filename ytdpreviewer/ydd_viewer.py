"""OpenIV-style 3D viewer for .ydd (pyglet + OpenGL)."""

from __future__ import annotations

import ctypes
import math
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyglet

pyglet.options["shadow_window"] = False

from pyglet.gl import (
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_RGBA,
    GL_UNSIGNED_BYTE,
    GL_DEPTH_TEST,
    GL_LEQUAL,
    GL_LIGHT0,
    GL_AMBIENT,
    GL_DIFFUSE,
    GL_POSITION,
    GL_LIGHTING,
    GL_COLOR_MATERIAL,
    GL_FRONT_AND_BACK,
    GL_AMBIENT_AND_DIFFUSE,
    GL_NORMALIZE,
    GL_LINES,
    GL_MODELVIEW,
    GL_MODULATE,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_POINTS,
    GL_POLYGON_OFFSET_LINE,
    GL_PROJECTION,
    GL_QUADS,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    GL_TEXTURE_ENV,
    GL_TEXTURE_ENV_MODE,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TEXTURE0,
    GL_TEXTURE1,
    GL_REPEAT,
    GL_SCISSOR_TEST,
    GL_TRIANGLES,
    GL_VERTEX_SHADER,
    GL_FRAGMENT_SHADER,
    GL_COMPILE_STATUS,
    GL_LINK_STATUS,
    glBegin,
    glBindTexture,
    glBlendFunc,
    glClear,
    glClearColor,
    glColor3f,
    glDepthFunc,
    glDisable,
    glEnable,
    glEnd,
    glLineWidth,
    glLightfv,
    glColorMaterial,
    glLoadIdentity,
    glMatrixMode,
    glOrtho,
    glPointSize,
    glPolygonOffset,
    glPopMatrix,
    glPushMatrix,
    glRotatef,
    glScissor,
    glTexEnvf,
    glTexParameteri,
    glTranslatef,
    glReadPixels,
    glVertex3f,
    glViewport,
    glActiveTexture,
    glAttachShader,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glShaderSource,
    glUniform1i,
    glUseProgram,
    GLchar,
    GLint,
    GLfloat,
)
from pyglet.gl.glu import gluLookAt, gluPerspective
from pyglet.window import key, mouse

from ytdpreviewer.app_icon import apply_pyglet_icon
from ytdpreviewer.ui_theme import APP_CREDIT
from ytdpreviewer.viewer_prefs import ViewerColorPrefs, load_color_prefs, save_color_prefs
from ytdpreviewer.win_dialog import pick_color, pick_open_file, pick_save_file
from ytdpreviewer.ydd_export import export_ydd_to_obj
from ytdpreviewer.ydd_loader import (
    LOD_LABELS,
    YddModel,
    add_ytd_to_model,
    all_texture_names,
    default_diffuse_texture_key,
    format_vertex_colour_lines,
    load_ydd,
    model_vertex_colour_stats,
    next_lod,
    resolve_lod,
    save_embedded_textures,
    texture_to_pil,
    _texture_key,
)


SIDEBAR_W = 0
PANEL_BG = (34, 34, 36, 230)
PANEL_FG = (220, 220, 220)
PANEL_DIM = (150, 150, 150)
ACCENT = (90, 156, 220)
VIEW_BG = (0.12, 0.12, 0.13, 1.0)
FLOOR_GRID_COLOR = (0.32, 0.32, 0.34)
MESH_GRID_COLOR = (0.42, 0.44, 0.48)
FALLBACK = (0.78, 0.55, 0.35)
UI_FONT = ("Segoe UI", "Calibri", "Trebuchet MS", "Arial")
UI_FONT_SIZE = 12
UI_FONT_SIZE_SMALL = 10
TEXTURE_PANEL_MAX_ROWS = 8
LOD_TITLE_COLOR = (205, 178, 70)

MATERIAL_VERTEX_SHADER = """
#version 120
varying vec3 eye_position;
varying vec3 surface_normal;
varying vec2 texcoord;
varying vec4 vertex_color;

void main() {
    vec4 eye = gl_ModelViewMatrix * gl_Vertex;
    eye_position = eye.xyz;
    surface_normal = normalize(gl_NormalMatrix * gl_Normal);
    texcoord = gl_MultiTexCoord0.xy;
    vertex_color = gl_Color;
    gl_Position = gl_ProjectionMatrix * eye;
}
"""

MATERIAL_FRAGMENT_SHADER = """
#version 120
uniform sampler2D diffuse_map;
uniform sampler2D normal_map;
uniform bool use_normal_map;
uniform bool use_lighting;

varying vec3 eye_position;
varying vec3 surface_normal;
varying vec2 texcoord;
varying vec4 vertex_color;

void main() {
    vec4 base = texture2D(diffuse_map, texcoord) * vertex_color;
    if (!use_lighting) {
        gl_FragColor = base;
        return;
    }

    vec3 normal = normalize(surface_normal);
    if (use_normal_map) {
        vec3 position_dx = dFdx(eye_position);
        vec3 position_dy = dFdy(eye_position);
        vec2 uv_dx = dFdx(texcoord);
        vec2 uv_dy = dFdy(texcoord);
        vec3 tangent = normalize(position_dx * uv_dy.y - position_dy * uv_dx.y);
        vec3 bitangent = normalize(-position_dx * uv_dy.x + position_dy * uv_dx.x);
        vec3 mapped = texture2D(normal_map, texcoord).xyz * 2.0 - 1.0;
        mapped.y = -mapped.y;
        normal = normalize(tangent * mapped.x + bitangent * mapped.y + normal * mapped.z);
    }

    vec3 light_direction = normalize(vec3(-0.35, 0.75, 0.60));
    float diffuse_light = max(dot(normal, light_direction), 0.0);
    vec3 color = base.rgb * (0.30 + 0.90 * diffuse_light);

    gl_FragColor = vec4(color, base.a);
}
"""


def _compile_shader(shader_type: int, source: str) -> int:
    shader = glCreateShader(shader_type)
    encoded = source.encode("utf-8")
    buffer = ctypes.create_string_buffer(encoded)
    pointer = ctypes.cast(buffer, ctypes.POINTER(GLchar))
    glShaderSource(shader, 1, ctypes.byref(pointer), None)
    glCompileShader(shader)
    status = GLint()
    glGetShaderiv(shader, GL_COMPILE_STATUS, ctypes.byref(status))
    if not status.value:
        length = 4096
        log = ctypes.create_string_buffer(length)
        glGetShaderInfoLog(shader, length, None, log)
        raise RuntimeError(log.value.decode("utf-8", "replace"))
    return int(shader)


def _create_material_program() -> int:
    vertex = _compile_shader(GL_VERTEX_SHADER, MATERIAL_VERTEX_SHADER)
    fragment = _compile_shader(GL_FRAGMENT_SHADER, MATERIAL_FRAGMENT_SHADER)
    program = glCreateProgram()
    glAttachShader(program, vertex)
    glAttachShader(program, fragment)
    glLinkProgram(program)
    status = GLint()
    glGetProgramiv(program, GL_LINK_STATUS, ctypes.byref(status))
    if not status.value:
        length = 4096
        log = ctypes.create_string_buffer(length)
        glGetProgramInfoLog(program, length, None, log)
        raise RuntimeError(log.value.decode("utf-8", "replace"))
    return int(program)


class MaterialTextureGroup(pyglet.graphics.Group):
    def __init__(
        self,
        program: int,
        diffuse,
        normal,
        *,
        use_normal: bool,
        use_lighting: bool,
    ) -> None:
        super().__init__()
        self.program = program
        self.diffuse = diffuse
        self.normal = normal or diffuse
        self.use_normal = bool(normal and use_normal)
        self.use_lighting = use_lighting

    def __eq__(self, other) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)

    def set_state(self) -> None:
        glUseProgram(self.program)
        for unit, uniform, texture in (
            (GL_TEXTURE0, b"diffuse_map", self.diffuse),
            (GL_TEXTURE1, b"normal_map", self.normal),
        ):
            glActiveTexture(unit)
            glEnable(texture.target)
            glBindTexture(texture.target, texture.id)
            glUniform1i(glGetUniformLocation(self.program, uniform), unit - GL_TEXTURE0)
        glUniform1i(glGetUniformLocation(self.program, b"use_normal_map"), self.use_normal)
        glUniform1i(glGetUniformLocation(self.program, b"use_lighting"), self.use_lighting)
        glActiveTexture(GL_TEXTURE0)

    def unset_state(self) -> None:
        glUseProgram(0)
        glActiveTexture(GL_TEXTURE1)
        glDisable(GL_TEXTURE_2D)
        glActiveTexture(GL_TEXTURE0)


def _gta_to_view_positions(positions: np.ndarray) -> np.ndarray:
    """GTA/RAGE Z-up -> OpenGL Y-up (rotate -90° around X)."""
    p = np.asarray(positions, dtype=np.float32)
    if p.size == 0:
        return p.reshape(0, 3)
    return np.stack([p[:, 0], p[:, 2], -p[:, 1]], axis=1)


def _gta_to_view_normals(normals: np.ndarray) -> np.ndarray:
    n = np.asarray(normals, dtype=np.float32)
    if n.size == 0:
        return n.reshape(0, 3)
    transformed = np.stack([n[:, 0], n[:, 2], -n[:, 1]], axis=1)
    lengths = np.linalg.norm(transformed, axis=1, keepdims=True)
    lengths = np.maximum(lengths, 1e-8)
    return transformed / lengths


def _project_root() -> Path:
    from ytdpreviewer.paths import app_dir

    if getattr(sys, "frozen", False):
        return app_dir()
    return Path(__file__).resolve().parent.parent


def _python_for_gui() -> Path:
    """Prefer pythonw.exe so child processes do not open a console window."""
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.is_file():
            return pyw
    return exe


def _subprocess_no_window_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags} if flags else {}


def _hide_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def show_error(message: str, title: str = "YTD Previewer — YDD") -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        log = Path.home() / "AppData" / "Local" / "YTDPreviewer" / "ydd_error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(message, encoding="utf-8")


def show_info(message: str, title: str = "YTD Previewer — YDD") -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
    except Exception:
        show_error(message, title)


def _is_shell_scratch_ydd(path: Path) -> bool:
    """Explorer thumb temps must not open the 3D viewer (causes white window + spam)."""
    name = path.name.lower()
    if name.startswith("ytdprev_open_"):
        return False
    return name.startswith("ytdprev_") or name.startswith("yddprev_")


_recent_ydd_open: dict[str, float] = {}
_YDD_OPEN_DEBOUNCE_SEC = 1.5


def _prepare_ydd_open_path(ydd_path: str | Path) -> tuple[Path, Path | None]:
    """
    Return (path_to_open, ephemeral_copy_to_delete_later).

    Explorer may pass ytdprev_*.ydd from the shell thumbnail handler; copy to
    ytdprev_open_* so the file survives after the handler reclaims the temp file.
    """
    src = Path(ydd_path)
    name_lower = src.name.lower()

    if not src.is_file():
        if "ytdprev_" in name_lower:
            raise FileNotFoundError(
                f"Временный файл превью уже удалён:\n{src}\n\n"
                "Подождите секунду и снова откройте .ydd двойным щелчком по файлу в папке "
                "(не по иконке превью)."
            )
        raise FileNotFoundError(f"Файл не найден: {src}")

    resolved = src.resolve()
    if "ytdprev_" not in name_lower:
        return resolved, None

    dest = Path(tempfile.gettempdir()) / f"ytdprev_open_{uuid.uuid4().hex}.ydd"
    shutil.copy2(resolved, dest)
    return dest.resolve(), dest


def launch_ydd_viewer(ydd_path: str | Path, *, separate_process: bool = True) -> None:
    del separate_process
    src = Path(ydd_path)
    if _is_shell_scratch_ydd(src):
        return

    try:
        path, _copy = _prepare_ydd_open_path(ydd_path)
    except FileNotFoundError as exc:
        show_error(str(exc))
        return

    key = str(path).lower()
    now = time.monotonic()
    if now - _recent_ydd_open.get(key, 0.0) < _YDD_OPEN_DEBOUNCE_SEC:
        return
    _recent_ydd_open[key] = now

    import threading

    threading.Thread(
        target=run_viewer_safe,
        args=(path,),
        name="ydd-viewer",
        daemon=False,
    ).start()


@dataclass
class GpuMesh:
    drawable_index: int
    mesh_index: int
    vertex_list: pyglet.graphics.vertexdomain.VertexList
    edge_list: pyglet.graphics.vertexdomain.VertexList | None
    point_list: pyglet.graphics.vertexdomain.VertexList | None
    triangle_count: int
    vertex_count: int
    texture_name: str | None = None


@dataclass
class ViewerSettings:
    show_floor_grid: bool = False
    show_axis_gizmo: bool = True
    show_edges: bool = False
    show_geometry: bool = True
    show_vertices: bool = False
    show_texture: bool = True
    show_lighting: bool = True
    show_normal_map: bool = True
    show_mesh_vertex_colours: bool = False
    mesh_color: tuple[float, float, float] = FALLBACK
    edge_color: tuple[float, float, float] = MESH_GRID_COLOR
    vertex_color: tuple[float, float, float] = (0.9, 0.9, 0.2)


class YddViewerWindow(pyglet.window.Window):
    def __init__(self, model: YddModel, *, thumbnail_size: int | None = None) -> None:
        self._thumbnail_mode = thumbnail_size is not None
        thumb_side = max(32, min(int(thumbnail_size or 128), 512)) if self._thumbnail_mode else 0
        win_w = thumb_side if self._thumbnail_mode else 1280
        win_h = thumb_side if self._thumbnail_mode else 800

        config = pyglet.gl.Config(double_buffer=True, depth_size=24)
        super().__init__(
            width=win_w,
            height=win_h,
            caption="" if self._thumbnail_mode else f"{model.path.name} — просмотр модели YTD Previewer",
            resizable=not self._thumbnail_mode,
            vsync=not self._thumbnail_mode,
            visible=False,
            config=config,
        )
        if self._thumbnail_mode:
            try:
                self.set_location(-32000, -32000)
            except Exception:
                pass
        if not self._thumbnail_mode:
            self._center_on_screen()
            apply_pyglet_icon(self)

        self.model = model
        color_prefs = load_color_prefs(
            mesh_default=FALLBACK,
            edge_default=MESH_GRID_COLOR,
            vertex_default=(0.9, 0.9, 0.2),
        )
        self.settings = ViewerSettings(
            mesh_color=color_prefs.mesh_color,
            edge_color=color_prefs.edge_color,
            vertex_color=color_prefs.vertex_color,
        )
        if self._thumbnail_mode:
            self.settings.show_floor_grid = False
            self.settings.show_axis_gizmo = False
            self.settings.show_edges = False
            self.settings.show_vertices = False
        self.lod = resolve_lod(model, "high")

        self._center, self._radius, self._floor_y = self._bounds()
        self.cam_yaw = 35.0
        self.cam_pitch = 18.0
        self.cam_dist = max(self._radius * 2.4, 1.5)
        self._drag: tuple[int, int] | None = None
        self._fps = 0.0
        self._fps_time = time.perf_counter()
        self._frames = 0
        self._status = ""

        self.batch = pyglet.graphics.Batch()
        self.edge_batch = pyglet.graphics.Batch()
        self.point_batch = pyglet.graphics.Batch()
        self._btn_detail: tuple[int, int, int, int] | None = None
        self._btn_edges: tuple[int, int, int, int] | None = None
        self._btn_vertices: tuple[int, int, int, int] | None = None
        self._btn_texture: tuple[int, int, int, int] | None = None
        self._btn_lighting: tuple[int, int, int, int] | None = None
        self._btn_normal_map: tuple[int, int, int, int] | None = None
        self._btn_vtx_colours: tuple[int, int, int, int] | None = None
        self._btn_floor_grid: tuple[int, int, int, int] | None = None
        self._btn_mesh_color: tuple[int, int, int, int] | None = None
        self._btn_edge_color: tuple[int, int, int, int] | None = None
        self._btn_vertex_color: tuple[int, int, int, int] | None = None
        self._btn_add_texture: tuple[int, int, int, int] | None = None
        self._btn_export_obj: tuple[int, int, int, int] | None = None
        self._texture_hits: list[tuple[str, tuple[int, int, int, int]]] = []
        self._textures: dict[str, pyglet.image.Texture] = {}
        self._selected_texture: str | None = None
        self._texture_override: str | None = None
        self._texture_scroll = 0
        self._texture_panel_rect: tuple[int, int, int, int] | None = None
        self._gpu_meshes: list[GpuMesh] = []
        self._material_program: int | None = None
        self._init_texture_selection()
        default_key = default_diffuse_texture_key(self.model)
        if default_key:
            self._texture_override = default_key
            self._selected_texture = default_key
        self._build_gpu()
        self.switch_to()
        glClearColor(*VIEW_BG)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._thumbnail_mode:
            return
        self.set_visible(True)
        self.dispatch_events()
        pyglet.clock.schedule_once(self._raise_to_front, 0.1)

    def capture_thumbnail_image(self):
        """Render one 3D frame and return a PIL RGBA image (thumbnail mode)."""
        import ctypes

        from PIL import Image

        self.switch_to()
        pyglet.clock.tick(poll=True)
        try:
            self.dispatch_events()
        except Exception:
            pass

        self._draw_scene()
        w, h = max(1, self.width), max(1, self.height)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf)
        img = Image.frombytes("RGBA", (w, h), bytes(buf))
        return img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def _raise_to_front(self, _dt: float) -> None:
        from ytdpreviewer.window_front import focus_pyglet_window

        focus_pyglet_window(self)

    def _center_on_screen(self) -> None:
        try:
            screen = self.display.get_default_screen()
            x = max(0, (screen.width - self.width) // 2)
            y = max(0, (screen.height - self.height) // 2)
            self.set_location(x, y)
        except Exception:
            pass

    def _make_label(
        self,
        text: str,
        x: int,
        y: int,
        *,
        size: int = UI_FONT_SIZE,
        color: tuple[int, int, int] = PANEL_FG,
        anchor_x: str = "left",
        anchor_y: str = "top",
        **kwargs,
    ) -> pyglet.text.Label:
        return pyglet.text.Label(
            text,
            x=x,
            y=y,
            font_name=UI_FONT,
            font_size=size,
            color=(*color, 255),
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            **kwargs,
        )

    def _bounds(self) -> tuple[np.ndarray, float, float]:
        minimum: np.ndarray | None = None
        maximum: np.ndarray | None = None
        for drawable in self.model.drawables_for_lod(self.lod):
            for mesh in drawable.meshes:
                if len(mesh.positions) == 0:
                    continue
                points = _gta_to_view_positions(np.asarray(mesh.positions, dtype=np.float32))
                mesh_min = points.min(axis=0)
                mesh_max = points.max(axis=0)
                minimum = mesh_min if minimum is None else np.minimum(minimum, mesh_min)
                maximum = mesh_max if maximum is None else np.maximum(maximum, mesh_max)
        if minimum is None or maximum is None:
            center = np.zeros(3, dtype=np.float64)
            return center, 1.0, 0.0
        center = (minimum + maximum) * 0.5
        radius = float(np.linalg.norm(maximum - minimum) * 0.5)
        return center, max(radius, 0.05), float(minimum[1])

    def _init_texture_selection(self) -> None:
        names = self._all_texture_names()
        if not names:
            return
        default_key = default_diffuse_texture_key(self.model)
        if default_key and default_key in names:
            self._selected_texture = default_key
            return
        for drawable in self.model.drawables_for_lod(self.lod):
            for mesh in drawable.meshes:
                if mesh.texture_name and self.model.resolve_texture(mesh.texture_name):
                    self._selected_texture = _texture_key(mesh.texture_name)
                    return
        self._selected_texture = names[0]

    def _all_texture_names(self) -> list[str]:
        return all_texture_names(self.model, self.lod)

    def _load_texture(self, name: str | None) -> pyglet.image.Texture | None:
        if not name:
            return None
        key = _texture_key(name)
        if key in self._textures:
            return self._textures[key]
        source = self.model.resolve_texture(name)
        if source is None:
            return None
        try:
            image = texture_to_pil(source)
            rgba = image.convert("RGBA")
            tex = pyglet.image.ImageData(
                rgba.width,
                rgba.height,
                "RGBA",
                rgba.tobytes(),
            ).get_texture()
            glBindTexture(tex.target, tex.id)
            glTexParameteri(tex.target, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameteri(tex.target, GL_TEXTURE_WRAP_T, GL_REPEAT)
            self._textures[key] = tex
            return tex
        except Exception:
            return None

    def _select_texture(self, name: str, *, apply_override: bool = True) -> None:
        key = _texture_key(name)
        self._selected_texture = key
        if apply_override:
            source = self.model.resolve_texture(name)
            if source is None:
                self._status = f"Текстура не найдена: {name}"
                return
            try:
                texture_to_pil(source)
            except Exception:
                self._status = f"Не удалось декодировать: {name}"
                return
            self._texture_override = key
            self._textures.clear()
            try:
                self._rebuild_geometry(preserve_camera=True)
            except Exception as exc:
                self._texture_override = None
                self._status = f"Ошибка текстуры: {exc}"
                return
        self._status = f"Текстура: {name}"
        self._ensure_texture_visible()

    def _ensure_texture_visible(self) -> None:
        names = self._all_texture_names()
        if not names or self._selected_texture not in names:
            return
        index = names.index(self._selected_texture)
        max_scroll = max(0, len(names) - TEXTURE_PANEL_MAX_ROWS)
        self._texture_scroll = max(0, min(self._texture_scroll, max_scroll))
        if index < self._texture_scroll:
            self._texture_scroll = index
        elif index >= self._texture_scroll + TEXTURE_PANEL_MAX_ROWS:
            self._texture_scroll = index - TEXTURE_PANEL_MAX_ROWS + 1

    def _cycle_texture(self, step: int) -> None:
        names = self._all_texture_names()
        if not names:
            return
        if self._selected_texture not in names:
            self._select_texture(names[0])
            return
        index = names.index(self._selected_texture)
        self._select_texture(names[(index + step) % len(names)])

    def _export_obj(self) -> None:
        # Modal dialogs from pyglet mouse handlers often fail; run next frame.
        pyglet.clock.schedule_once(self._export_obj_run, 0.05)

    def _export_obj_run(self, _dt: float) -> None:
        default_name = f"{self.model.path.stem}_{resolve_lod(self.model, self.lod)}.obj"
        try:
            path = pick_save_file(
                title="Экспорт OBJ",
                initial_dir=self.model.path.parent,
                initial_file=default_name,
                filetypes=[("Wavefront OBJ", "*.obj"), ("Все файлы", "*.*")],
                defaultextension="obj",
            )
        except Exception as exc:
            show_error(f"Не удалось открыть диалог сохранения:\n{exc}")
            return
        if path is None:
            return
        try:
            from ytdpreviewer.export_progress import run_with_export_progress

            def work(report) -> Path:
                report(1, 2, "Запись OBJ…")
                return export_ydd_to_obj(
                    self.model,
                    path,
                    lod=self.lod,
                    texture_override=self._texture_override,
                )

            out = run_with_export_progress("Экспорт YDD → OBJ", work, initial_total=2)
            self._status = f"Экспорт: {out.name}"
            show_info(f"Модель сохранена:\n{out}")
        except Exception as exc:
            self._status = f"Ошибка экспорта: {exc}"
            show_error(f"Ошибка экспорта:\n{exc}")

    def _add_texture_dialog(self) -> None:
        parent = getattr(self, "_hwnd", None)
        path = pick_open_file(
            title="Добавить YTD",
            initial_dir=self.model.path.parent,
            parent_hwnd=parent,
        )
        if path is None:
            return

        added = add_ytd_to_model(self.model, path)
        if not added:
            self._status = "В YTD нет новых текстур"
            return
        self._textures.clear()
        self._select_texture(added[0])
        self._status = f"Добавлено текстур: {len(added)}"

    def _mesh_texcoords(self, mesh) -> list[float]:
        data: list[float] = []
        for u, v in mesh.uvs:
            data.extend([float(u), float(v)])
        return data

    def _toggle_texture(self) -> None:
        self.settings.show_texture = not self.settings.show_texture
        self._rebuild_geometry(preserve_camera=True)
        self._status = f"Текстура: {'вкл' if self.settings.show_texture else 'выкл'}"

    def _toggle_lighting(self) -> None:
        self.settings.show_lighting = not self.settings.show_lighting
        self._rebuild_geometry(preserve_camera=True)

    def _toggle_normal_map(self) -> None:
        self.settings.show_normal_map = not self.settings.show_normal_map
        self._rebuild_geometry(preserve_camera=True)

    def _toggle_edges(self) -> None:
        self.settings.show_edges = not self.settings.show_edges
        if self.settings.show_edges:
            self._rebuild_geometry(preserve_camera=True)

    def _toggle_vertices(self) -> None:
        self.settings.show_vertices = not self.settings.show_vertices
        if self.settings.show_vertices:
            self._rebuild_geometry(preserve_camera=True)

    def _toggle_mesh_vertex_colours(self) -> None:
        meshes, verts, _sample = model_vertex_colour_stats(self.model, lod=self.lod)
        if meshes == 0:
            self._status = "В YDD нет Colour0/Colour1 на вершинах"
            return
        self.settings.show_mesh_vertex_colours = not self.settings.show_mesh_vertex_colours
        self._rebuild_geometry(preserve_camera=True)
        if self.settings.show_mesh_vertex_colours:
            self._status = f"Цвета вершин: вкл ({meshes} меш., {verts:,} vtx)".replace(",", " ")
        else:
            self._status = "Цвета вершин: выкл"

    @staticmethod
    def _colour_byte(value: float) -> int:
        v = float(value)
        if v > 1.0:
            v /= 255.0
        return int(max(0, min(255, round(v * 255))))

    def _mesh_vertex_colour_c4b(self, mesh) -> list[int] | None:
        if not self.settings.show_mesh_vertex_colours:
            return None
        channel = mesh.colours0 if mesh.colours0 else mesh.colours1
        if len(channel) != mesh.vertex_count:
            return None
        data: list[int] = []
        for r, g, b, a in channel:
            data.extend(
                (
                    self._colour_byte(r),
                    self._colour_byte(g),
                    self._colour_byte(b),
                    self._colour_byte(a),
                )
            )
        return data

    def _rebuild_geometry(self, *, preserve_camera: bool = False) -> None:
        if preserve_camera:
            center = np.copy(self._center)
            floor_y = self._floor_y
            cam_dist = self.cam_dist
            cam_yaw = self.cam_yaw
            cam_pitch = self.cam_pitch

        self._center, self._radius, self._floor_y = self._bounds()

        if preserve_camera:
            self._center = center
            self._floor_y = floor_y
            self.cam_dist = cam_dist
            self.cam_yaw = cam_yaw
            self.cam_pitch = cam_pitch

        self.batch = pyglet.graphics.Batch()
        self.edge_batch = pyglet.graphics.Batch()
        self.point_batch = pyglet.graphics.Batch()
        self._gpu_meshes.clear()
        self._build_gpu()

    def _cycle_lod(self) -> None:
        if len(self.model.available_lods) <= 1:
            return
        self.lod = next_lod(self.model, self.lod)
        self._rebuild_geometry(preserve_camera=True)
        self._status = f"Детализация: {LOD_LABELS.get(self.lod, self.lod)}"

    def _build_gpu(self) -> None:
        if self._material_program is None:
            try:
                self.switch_to()
                self._material_program = _create_material_program()
            except Exception:
                self._material_program = 0
        drawables = self.model.drawables_for_lod(self.lod)
        for drawable_index, drawable in enumerate(drawables):
            for mesh_index, mesh in enumerate(drawable.meshes):
                if not mesh.indices:
                    continue
                positions = _gta_to_view_positions(np.asarray(mesh.positions, dtype=np.float32))
                normals = _gta_to_view_normals(np.asarray(mesh.normals, dtype=np.float32))
                uvs_array = np.asarray(mesh.uvs, dtype=np.float32)
                if len(normals) != len(positions):
                    normals = np.tile(np.array([0.0, 1.0, 0.0], dtype=np.float32), (len(positions), 1))
                if len(uvs_array) != len(positions):
                    uvs_array = np.zeros((len(positions), 2), dtype=np.float32)

                coords = positions.reshape(-1).tolist()
                norms = normals.reshape(-1).tolist()
                texcoords = self._mesh_texcoords(mesh)

                indices = np.asarray(mesh.indices, dtype=np.uint32)
                vertex_count = len(positions)
                index_list = indices.reshape(-1).tolist()
                tex_name = self._texture_override or mesh.texture_name
                vtx_c4b = self._mesh_vertex_colour_c4b(mesh)
                texture = (
                    self._load_texture(tex_name)
                    if self.settings.show_texture and vtx_c4b is None
                    else None
                )
                if texture is not None:
                    normal_texture = (
                        self._load_texture(mesh.normal_texture_name)
                        if self.settings.show_normal_map
                        else None
                    )
                    group = (
                        MaterialTextureGroup(
                            self._material_program,
                            texture,
                            normal_texture,
                            use_normal=self.settings.show_normal_map,
                            use_lighting=self.settings.show_lighting,
                        )
                        if self._material_program
                        else pyglet.graphics.TextureGroup(texture)
                    )
                    fmt = (
                        ("v3f/static", coords),
                        ("n3f/static", norms),
                        ("t2f/static", texcoords),
                    )
                    if vtx_c4b is not None:
                        fmt = (*fmt, ("c4B/static", vtx_c4b))
                    vlist = self.batch.add_indexed(
                        vertex_count,
                        GL_TRIANGLES,
                        group,
                        index_list,
                        *fmt,
                    )
                elif vtx_c4b is not None:
                    vlist = self.batch.add_indexed(
                        vertex_count,
                        GL_TRIANGLES,
                        None,
                        index_list,
                        ("v3f/static", coords),
                        ("n3f/static", norms),
                        ("c4B/static", vtx_c4b),
                    )
                else:
                    mesh_rgb = self.settings.mesh_color
                    colors = [
                        component
                        for _ in range(vertex_count)
                        for component in (
                            int(mesh_rgb[0] * 255),
                            int(mesh_rgb[1] * 255),
                            int(mesh_rgb[2] * 255),
                        )
                    ]
                    vlist = self.batch.add_indexed(
                        vertex_count,
                        GL_TRIANGLES,
                        None,
                        index_list,
                        ("v3f/static", coords),
                        ("n3f/static", norms),
                        ("c3B/static", colors),
                    )

                edge_list = None
                if self.settings.show_edges:
                    triangles = indices.reshape(-1, 3)
                    edge_indices = np.column_stack(
                        (
                            triangles[:, 0],
                            triangles[:, 1],
                            triangles[:, 1],
                            triangles[:, 2],
                            triangles[:, 2],
                            triangles[:, 0],
                        )
                    ).reshape(-1).tolist()
                    edge_list = self.edge_batch.add_indexed(
                        vertex_count,
                        GL_LINES,
                        None,
                        edge_indices,
                        ("v3f/static", coords),
                    )

                point_list = None
                if self.settings.show_vertices:
                    if vtx_c4b is not None:
                        point_list = self.point_batch.add(
                            vertex_count, GL_POINTS, None, ("v3f/static", coords), ("c4B/static", vtx_c4b)
                        )
                    else:
                        point_list = self.point_batch.add(
                            vertex_count, GL_POINTS, None, ("v3f/static", coords)
                        )

                self._gpu_meshes.append(
                    GpuMesh(
                        drawable_index=drawable_index,
                        mesh_index=mesh_index,
                        vertex_list=vlist,
                        edge_list=edge_list,
                        point_list=point_list,
                        triangle_count=mesh.triangle_count,
                        vertex_count=mesh.vertex_count,
                        texture_name=mesh.texture_name,
                    )
                )

    def _viewport(self) -> tuple[int, int, int, int]:
        x = SIDEBAR_W
        y = 0
        w = max(1, self.width - SIDEBAR_W)
        h = max(1, self.height)
        return x, y, w, h

    def _camera_eye(self) -> tuple[float, float, float]:
        yaw = math.radians(self.cam_yaw)
        pitch = math.radians(self.cam_pitch)
        cx, cy, cz = self._center
        dist = self.cam_dist
        x = cx + dist * math.cos(pitch) * math.sin(yaw)
        y = cy + dist * math.sin(pitch)
        z = cz + dist * math.cos(pitch) * math.cos(yaw)
        return float(x), float(y), float(z)

    def _apply_camera(self) -> None:
        x, y, w, h = self._viewport()
        aspect = w / h
        glViewport(x, y, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45.0, aspect, max(self._radius * 0.01, 0.01), max(self._radius * 50.0, 100.0))
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        eye = self._camera_eye()
        cx, cy, cz = self._center
        gluLookAt(eye[0], eye[1], eye[2], float(cx), float(cy), float(cz), 0.0, 1.0, 0.0)

    def _setup_unlit(self, *, use_texture: bool) -> None:
        """Fixed-function shading without lights (avoids washed-out white on some GPUs)."""
        glDisable(GL_LIGHTING)
        glDisable(GL_COLOR_MATERIAL)
        glColor3f(1.0, 1.0, 1.0)
        if use_texture:
            glEnable(GL_TEXTURE_2D)
            glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        else:
            glDisable(GL_TEXTURE_2D)

    def _setup_lighting(self, *, use_texture: bool) -> None:
        """Soft camera-side light that works with textures and vertex colours."""
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_NORMALIZE)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glLightfv(GL_LIGHT0, GL_AMBIENT, (GLfloat * 4)(0.30, 0.30, 0.32, 1.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (GLfloat * 4)(0.90, 0.88, 0.84, 1.0))
        glLightfv(GL_LIGHT0, GL_POSITION, (GLfloat * 4)(-0.35, 0.75, 0.60, 0.0))
        glColor3f(1.0, 1.0, 1.0)
        if use_texture:
            glEnable(GL_TEXTURE_2D)
            glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
        else:
            glDisable(GL_TEXTURE_2D)

    def _draw_floor_grid(self) -> None:
        if not self.settings.show_floor_grid:
            return
        cx, _, cz = self._center
        floor_y = self._floor_y
        span = max(self._radius * 3.0, 2.0)
        step = max(span / 10.0, 0.1)
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_LIGHTING)
        glColor3f(*FLOOR_GRID_COLOR)
        glLineWidth(1.0)
        glBegin(GL_LINES)
        count = int(span / step)
        for i in range(-count, count + 1):
            offset = i * step
            glVertex3f(cx - span, floor_y, cz + offset)
            glVertex3f(cx + span, floor_y, cz + offset)
            glVertex3f(cx + offset, floor_y, cz - span)
            glVertex3f(cx + offset, floor_y, cz + span)
        glEnd()

    def _draw_axis_gizmo(self) -> None:
        if not self.settings.show_axis_gizmo:
            return
        x, y, w, h = self._viewport()
        gx, gy, gw, gh = x + 12, y + 12, 72, 72
        glEnable(GL_SCISSOR_TEST)
        glScissor(gx, gy, gw, gh)
        glViewport(gx, gy, gw, gh)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluPerspective(45.0, 1.0, 0.1, 50.0)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glTranslatef(0.0, 0.0, -3.2)
        glRotatef(self.cam_pitch, 1.0, 0.0, 0.0)
        glRotatef(self.cam_yaw, 0.0, 1.0, 0.0)
        glLineWidth(2.0)
        glBegin(GL_LINES)
        glColor3f(0.9, 0.25, 0.25)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(1.0, 0.0, 0.0)
        glColor3f(0.25, 0.85, 0.35)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 1.0, 0.0)
        glColor3f(0.35, 0.55, 0.9)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, 1.0)
        glEnd()
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glDisable(GL_SCISSOR_TEST)
        vx, vy, vw, vh = self._viewport()
        glViewport(vx, vy, vw, vh)

    def _sync_visibility(self) -> None:
        for gpu in self._gpu_meshes:
            gpu.vertex_list.visible = self.settings.show_geometry
            if gpu.edge_list is not None:
                gpu.edge_list.visible = self._show_edges()
            if gpu.point_list is not None:
                gpu.point_list.visible = self.settings.show_vertices

    def _visible_stats(self) -> tuple[int, int]:
        verts = sum(gpu.vertex_count for gpu in self._gpu_meshes)
        tris = sum(gpu.triangle_count for gpu in self._gpu_meshes)
        return verts, tris

    def _draw_scene(self) -> None:
        self.switch_to()
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glClearColor(*VIEW_BG)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._apply_camera()
        self._sync_visibility()

        self._draw_floor_grid()

        vtx_mode = self.settings.show_mesh_vertex_colours
        use_texture = self.settings.show_texture and not vtx_mode
        if self.settings.show_lighting:
            self._setup_lighting(use_texture=use_texture)
        else:
            self._setup_unlit(use_texture=use_texture)

        if self.settings.show_geometry:
            if self._gpu_meshes:
                self.batch.draw()
            else:
                self._draw_empty_scene_hint()

        glDisable(GL_LIGHTING)
        glDisable(GL_COLOR_MATERIAL)

        if self._show_edges():
            glDisable(GL_TEXTURE_2D)
            glEnable(GL_POLYGON_OFFSET_LINE)
            glPolygonOffset(-1.0, -1.0)
            glColor3f(*self.settings.edge_color)
            glLineWidth(1.0)
            self.edge_batch.draw()
            glDisable(GL_POLYGON_OFFSET_LINE)

        if self.settings.show_vertices:
            glDisable(GL_TEXTURE_2D)
            glColor3f(*self.settings.vertex_color)
            glPointSize(3.0)
            self.point_batch.draw()

        if self.settings.show_axis_gizmo:
            self._draw_axis_gizmo()

    def _draw_empty_scene_hint(self) -> None:
        glDisable(GL_TEXTURE_2D)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(-1, 1, -1, 1, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glColor3f(0.55, 0.55, 0.58)
        glBegin(GL_LINES)
        glVertex3f(-0.35, 0.0, 0.0)
        glVertex3f(0.35, 0.0, 0.0)
        glVertex3f(0.0, -0.35, 0.0)
        glVertex3f(0.0, 0.35, 0.0)
        glEnd()
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

    def _begin_ui(self) -> None:
        self.switch_to()
        glViewport(0, 0, self.width, self.height)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.width, 0, self.height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

    def _end_ui(self) -> None:
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glDisable(GL_BLEND)

    def _yes_no(self, value: bool) -> str:
        return "да" if value else "нет"

    def _draw_color_swatch(
        self,
        x: int,
        y: int,
        size: int,
        rgb: tuple[float, float, float],
    ) -> None:
        r, g, b = (int(component * 255) for component in rgb)
        pyglet.graphics.draw(
            4,
            GL_QUADS,
            ("v2f", (x - 1, y - 1, x + size + 1, y - 1, x + size + 1, y + size + 1, x - 1, y + size + 1)),
            ("c4B", (90, 90, 92, 255) * 4),
        )
        pyglet.graphics.draw(
            4,
            GL_QUADS,
            ("v2f", (x, y, x + size, y, x + size, y + size, x, y + size)),
            ("c4B", (r, g, b, 255) * 4),
        )

    def _swatch_rect(self, panel_x: int, panel_w: int, row_y: int, size: int = 16) -> tuple[int, int, int, int]:
        swatch_x = panel_x + panel_w - size - 12
        swatch_y = row_y - 8
        return swatch_x - 2, swatch_y - 2, swatch_x + size + 2, swatch_y + size + 2

    def _draw_color_row(
        self,
        panel_x: int,
        panel_w: int,
        row_y: int,
        label: str,
        rgb: tuple[float, float, float],
        attr: str,
    ) -> None:
        rect = self._swatch_rect(panel_x, panel_w, row_y)
        setattr(self, attr, rect)
        self._make_label(f"{label}:", panel_x + 10, row_y, color=LOD_TITLE_COLOR).draw()
        swatch_x, swatch_y, _, _ = rect
        self._draw_color_swatch(swatch_x + 2, swatch_y + 2, 16, rgb)

    def _draw_toggle_row(
        self,
        panel_x: int,
        panel_w: int,
        row_y: int,
        label: str,
        value: bool,
        attr: str,
        *,
        rgb: tuple[float, float, float] | None = None,
        color_attr: str | None = None,
    ) -> None:
        toggle_right = panel_x + panel_w - 36 if rgb is not None else panel_x + panel_w - 4
        setattr(self, attr, (panel_x + 4, row_y - 16, toggle_right, row_y + 4))
        self._make_label(f"{label}:", panel_x + 10, row_y, color=LOD_TITLE_COLOR).draw()
        self._make_label(self._yes_no(value), panel_x + 118, row_y, color=PANEL_FG).draw()
        if rgb is not None and color_attr is not None:
            rect = self._swatch_rect(panel_x, panel_w, row_y)
            setattr(self, color_attr, rect)
            swatch_x, swatch_y, _, _ = rect
            self._draw_color_swatch(swatch_x + 2, swatch_y + 2, 16, rgb)

    def _show_edges(self) -> bool:
        return self.settings.show_edges

    def _panel(self, x: int, y: int, w: int, h: int) -> None:
        pyglet.graphics.draw(4, GL_QUADS, ("v2f", (x, y, x + w, y, x + w, y + h, x, y + h)), ("c4B", PANEL_BG * 4))

    def _draw_ui(self) -> None:
        self._begin_ui()

        x, _, vw, _ = self._viewport()
        verts, tris = self._visible_stats()
        self._panel(x + 10, self.height - 96, 210, 86)
        stats = [
            f"FPS: {self._fps:.1f}",
            f"Полигоны: {tris:,}".replace(",", " "),
            f"Вертексы: {verts:,}".replace(",", " "),
        ]
        for i, line in enumerate(stats):
            self._make_label(line, x + 18, self.height - 28 - i * 22).draw()

        panel_w, panel_h = 268, 300
        panel_x = x + vw - panel_w - 10
        panel_y = self.height - panel_h - 10
        self._panel(panel_x, panel_y, panel_w, panel_h)

        row_y = panel_y + panel_h - 14
        row_step = 24
        mesh_colours, vtx_count, sample_rgba = model_vertex_colour_stats(self.model, lod=self.lod)
        resolved = resolve_lod(self.model, self.lod)
        detail_label = LOD_LABELS.get(resolved, resolved)
        self._btn_detail = (panel_x + 4, row_y - 16, panel_x + panel_w - 4, row_y + 4)
        self._make_label("Детализация:", panel_x + 10, row_y, color=LOD_TITLE_COLOR).draw()
        self._make_label(detail_label, panel_x + 118, row_y, color=PANEL_FG).draw()

        row_y -= row_step
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Сетка пола",
            self.settings.show_floor_grid,
            "_btn_floor_grid",
        )

        row_y -= row_step
        self._draw_color_row(panel_x, panel_w, row_y, "Модель", self.settings.mesh_color, "_btn_mesh_color")

        row_y -= row_step
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Свет",
            self.settings.show_lighting,
            "_btn_lighting",
        )

        row_y -= row_step
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Нормали",
            self.settings.show_normal_map,
            "_btn_normal_map",
        )

        row_y -= row_step
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Рёбра",
            self.settings.show_edges,
            "_btn_edges",
            rgb=self.settings.edge_color,
            color_attr="_btn_edge_color",
        )

        row_y -= row_step
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Вершины",
            self.settings.show_vertices,
            "_btn_vertices",
            rgb=self.settings.vertex_color,
            color_attr="_btn_vertex_color",
        )

        row_y -= row_step
        self._draw_toggle_row(panel_x, panel_w, row_y, "Текстура", self.settings.show_texture, "_btn_texture")

        row_y -= row_step
        has_vtx = mesh_colours > 0
        self._draw_toggle_row(
            panel_x,
            panel_w,
            row_y,
            "Цвета vtx",
            self.settings.show_mesh_vertex_colours if has_vtx else False,
            "_btn_vtx_colours",
        )

        row_y -= row_step
        if has_vtx:
            ch_label = "Colour0" if any(
                m.colours0 for d in self.model.drawables_for_lod(self.lod) for m in d.meshes
            ) else "Colour1"
            self._make_label(
                f"Мешей {mesh_colours}  vtx {vtx_count:,}".replace(",", " "),
                panel_x + 10,
                row_y,
                size=UI_FONT_SIZE_SMALL,
                color=PANEL_DIM,
                width=panel_w - 16,
            ).draw()
            row_y -= 17
            if sample_rgba is not None:
                byte_line, float_line = format_vertex_colour_lines(sample_rgba)
                self._make_label(
                    byte_line,
                    panel_x + 10,
                    row_y,
                    size=UI_FONT_SIZE_SMALL,
                    color=PANEL_FG,
                    width=panel_w - 16,
                ).draw()
                row_y -= 17
                self._make_label(
                    float_line,
                    panel_x + 10,
                    row_y,
                    size=UI_FONT_SIZE_SMALL,
                    color=PANEL_DIM,
                    width=panel_w - 16,
                ).draw()
                row_y -= 17
            self._make_label(
                f"Канал: {ch_label}",
                panel_x + 10,
                row_y,
                size=UI_FONT_SIZE_SMALL - 1,
                color=PANEL_DIM,
                width=panel_w - 16,
            ).draw()

        self._draw_texture_panel(x, vw)

        hint = (
            self._status
            or "ЛКМ — камера, G — сетка пола, P — текстура, C — vtx, E/V — рёбра/вершины"
        )
        self._make_label(
            hint,
            x + 12,
            12,
            size=UI_FONT_SIZE_SMALL,
            color=PANEL_DIM,
            anchor_y="bottom",
            width=vw - 24,
        ).draw()

        self._make_label(
            APP_CREDIT,
            x + vw - 12,
            12,
            size=UI_FONT_SIZE_SMALL - 1,
            color=PANEL_DIM,
            anchor_x="right",
            anchor_y="bottom",
        ).draw()

        self._end_ui()

    def _draw_texture_panel(self, x: int, vw: int) -> None:
        names = self._all_texture_names()
        panel_w = 280
        row_h = 18
        max_rows = TEXTURE_PANEL_MAX_ROWS
        total = len(names)
        max_scroll = max(0, total - max_rows)
        self._texture_scroll = max(0, min(self._texture_scroll, max_scroll))

        list_rows = max(1, min(max_rows, total))
        panel_h = 76 + list_rows * row_h
        panel_x = x + vw - panel_w - 10
        panel_y = 10
        self._texture_panel_rect = (panel_x, panel_y, panel_x + panel_w, panel_y + panel_h)

        self._panel(panel_x, panel_y, panel_w, panel_h)
        self._make_label("Текстуры:", panel_x + 10, panel_y + panel_h - 12, color=LOD_TITLE_COLOR).draw()

        add_y = panel_y + panel_h - 34
        export_y = add_y - 24
        half_w = (panel_w - 16) // 2
        self._btn_add_texture = (panel_x + 4, add_y - 14, panel_x + 4 + half_w, add_y + 4)
        self._btn_export_obj = (panel_x + 8 + half_w, add_y - 14, panel_x + panel_w - 4, add_y + 4)
        self._make_label("[+] YTD", panel_x + 10, add_y, color=ACCENT).draw()
        self._make_label("[→] OBJ", panel_x + 14 + half_w, add_y, color=ACCENT).draw()

        self._texture_hits = []
        row_y = export_y - 6
        if not names:
            self._make_label("(нет текстур)", panel_x + 10, row_y, size=UI_FONT_SIZE_SMALL, color=PANEL_DIM).draw()
            return

        start = self._texture_scroll
        for name in names[start : start + max_rows]:
            key = _texture_key(name)
            selected = key == self._selected_texture
            prefix = "> " if selected else "  "
            color = ACCENT if selected else PANEL_DIM
            self._texture_hits.append((name, (panel_x + 4, row_y - 14, panel_x + panel_w - 4, row_y + 4)))
            self._make_label(
                f"{prefix}{name}",
                panel_x + 10,
                row_y,
                size=UI_FONT_SIZE_SMALL,
                color=color,
                width=panel_w - 20,
            ).draw()
            row_y -= row_h

    def on_draw(self) -> None:
        try:
            self._draw_scene()
            self._draw_ui()
        except Exception as exc:
            self.switch_to()
            glClearColor(*VIEW_BG)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            self._status = f"Ошибка отрисовки: {exc}"
            _log_viewer_error(traceback.format_exc())
            try:
                self._begin_ui()
                self._make_label(
                    self._status,
                    12,
                    self.height // 2,
                    color=(240, 120, 120),
                    anchor_y="center",
                ).draw()
                self._end_ui()
            except Exception:
                pass
        self._frames += 1
        now = time.perf_counter()
        if now - self._fps_time >= 0.5:
            self._fps = self._frames / (now - self._fps_time)
            self._frames = 0
            self._fps_time = now

    def on_resize(self, width: int, height: int) -> None:
        super().on_resize(width, height)

    def on_mouse_press(self, x: int, y: int, button, modifiers) -> None:
        if button == mouse.LEFT:
            if self._ui_click(x, y):
                return
            self._drag = (x, y)

    def on_mouse_drag(self, x: int, y: int, dx: int, dy: int, buttons, modifiers) -> None:
        if buttons & mouse.LEFT and self._drag is not None:
            self.cam_yaw -= dx * 0.4
            self.cam_pitch = max(-89.0, min(89.0, self.cam_pitch - dy * 0.35))

    def on_mouse_release(self, x: int, y: int, button, modifiers) -> None:
        if button == mouse.LEFT:
            self._drag = None

    def on_mouse_scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        if self._hit(self._texture_panel_rect, x, y) and scroll_y:
            self._cycle_texture(-int(scroll_y))
            return
        factor = 0.9 if scroll_y > 0 else 1.1
        self.cam_dist = max(self._radius * 0.2, min(self._radius * 20.0, self.cam_dist * factor))

    def _hit(self, rect: tuple[int, int, int, int] | None, x: int, y: int) -> bool:
        if rect is None:
            return False
        x0, y0, x1, y1 = rect
        return x0 <= x <= x1 and y0 <= y <= y1

    def _save_color_prefs(self) -> None:
        save_color_prefs(
            ViewerColorPrefs(
                mesh_color=self.settings.mesh_color,
                edge_color=self.settings.edge_color,
                vertex_color=self.settings.vertex_color,
            )
        )

    def _pick_viewer_color(
        self,
        title: str,
        current: tuple[float, float, float],
    ) -> tuple[float, float, float] | None:
        return pick_color(
            title=title,
            initial_rgb=current,
            parent_hwnd=getattr(self, "_hwnd", None),
        )

    def _set_mesh_color(self) -> None:
        picked = self._pick_viewer_color("Цвет модели", self.settings.mesh_color)
        if picked is None:
            return
        self.settings.mesh_color = picked
        if not self.settings.show_texture:
            self._rebuild_geometry(preserve_camera=True)
        self._save_color_prefs()
        self._status = "Цвет модели изменён"

    def _set_edge_color(self) -> None:
        picked = self._pick_viewer_color("Цвет рёбер", self.settings.edge_color)
        if picked is None:
            return
        self.settings.edge_color = picked
        self._save_color_prefs()
        self._status = "Цвет рёбер изменён"

    def _set_vertex_color(self) -> None:
        picked = self._pick_viewer_color("Цвет вершин", self.settings.vertex_color)
        if picked is None:
            return
        self.settings.vertex_color = picked
        self._save_color_prefs()
        self._status = "Цвет вершин изменён"

    def _ui_click(self, x: int, y: int) -> bool:
        if self._hit(self._btn_export_obj, x, y):
            self._export_obj()
            return True
        if self._hit(self._btn_mesh_color, x, y):
            self._set_mesh_color()
            return True
        if self._hit(self._btn_edge_color, x, y):
            self._set_edge_color()
            return True
        if self._hit(self._btn_vertex_color, x, y):
            self._set_vertex_color()
            return True
        if self._hit(self._btn_detail, x, y):
            self._cycle_lod()
            return True
        if self._hit(self._btn_floor_grid, x, y):
            self.settings.show_floor_grid = not self.settings.show_floor_grid
            return True
        if self._hit(self._btn_lighting, x, y):
            self._toggle_lighting()
            return True
        if self._hit(self._btn_normal_map, x, y):
            self._toggle_normal_map()
            return True
        if self._hit(self._btn_edges, x, y):
            self._toggle_edges()
            return True
        if self._hit(self._btn_vertices, x, y):
            self._toggle_vertices()
            return True
        if self._hit(self._btn_texture, x, y):
            self._toggle_texture()
            return
        if self._hit(self._btn_vtx_colours, x, y):
            self._toggle_mesh_vertex_colours()
            return True
        if self._hit(self._btn_add_texture, x, y):
            self._add_texture_dialog()
            return True
        for name, rect in self._texture_hits:
            if self._hit(rect, x, y):
                self._select_texture(name)
                return True
        return False

    def on_key_press(self, symbol, modifiers) -> None:
        from ytdpreviewer.hotkeys import pyglet_ctrl_letter, pyglet_key_matches

        if pyglet_key_matches(symbol, key.G):
            self.settings.show_floor_grid = not self.settings.show_floor_grid
        elif pyglet_key_matches(symbol, key.L):
            self._toggle_lighting()
        elif pyglet_key_matches(symbol, key.N):
            self._toggle_normal_map()
        elif pyglet_key_matches(symbol, key.D):
            self._cycle_lod()
        elif pyglet_key_matches(symbol, key.E):
            self._toggle_edges()
        elif pyglet_key_matches(symbol, key.V):
            self._toggle_vertices()
        elif pyglet_key_matches(symbol, key.P):
            self._toggle_texture()
        elif pyglet_key_matches(symbol, key.C):
            self._toggle_mesh_vertex_colours()
        elif pyglet_key_matches(symbol, key.H):
            self.settings.show_geometry = not self.settings.show_geometry
        elif pyglet_key_matches(symbol, key.T):
            try:
                from ytdpreviewer.export_progress import run_with_export_progress

                def work(report) -> tuple[Path, int]:
                    return save_embedded_textures(self.model, on_progress=report)

                from ytdpreviewer.ydd_loader import _textures_for_export

                folder, count = run_with_export_progress(
                    "Экспорт текстур YDD",
                    work,
                    initial_total=max(1, len(_textures_for_export(self.model))),
                )
                self._status = f"Текстуры сохранены ({count}): {folder.name}"
            except Exception as exc:
                self._status = f"Ошибка экспорта: {exc}"
        elif pyglet_ctrl_letter(symbol, "a", modifiers):
            self._add_texture_dialog()
        elif pyglet_key_matches(symbol, key.BRACKETLEFT):
            self._cycle_texture(-1)
        elif pyglet_key_matches(symbol, key.BRACKETRIGHT):
            self._cycle_texture(1)
        elif symbol == key.ESCAPE:
            self.close()


def _log_viewer_error(text: str) -> None:
    try:
        log = Path.home() / "AppData" / "Local" / "YTDPreviewer" / "ydd_error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass


def run_viewer(ydd_path: str | Path) -> None:
    path, ephemeral = _prepare_ydd_open_path(ydd_path)
    try:
        model = load_ydd(path)
        if not model.available_lods:
            raise ValueError("В YDD нет геометрии для отображения")

        window = YddViewerWindow(model)
        if not window._gpu_meshes:
            window._status = "Нет треугольников на выбранном LOD — попробуйте D (детализация)"

        pyglet.app.run()
    finally:
        if ephemeral is not None:
            try:
                ephemeral.unlink(missing_ok=True)
            except OSError:
                pass


def run_viewer_safe(ydd_path: str | Path) -> None:
    _hide_console()
    try:
        run_viewer(ydd_path)
    except Exception:
        msg = traceback.format_exc()
        _log_viewer_error(msg)
        show_error(msg)


def open_preview_3d(ydd_path: str | Path, master=None) -> None:
    del master
    launch_ydd_viewer(ydd_path)


def open_preview_3d_toplevel(master, ydd_path: str | Path) -> None:
    del master
    launch_ydd_viewer(ydd_path)
