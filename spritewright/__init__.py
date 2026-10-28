"""spritewright - scriptable pixel-art toolkit (no GUI, everything outputs files).

    import spritewright as sw
    cv = sw.Canvas(32, 32, "pico-8")
    cv.rect(4, 4, 8, 8, 12).save("out.png", scale=8)
"""
from .errors import ColorError, GridError, PixelError, SourceError
from .palette import (PALETTE_DIR, ROOT, TRANSPARENT, Palette, generate_ramp, luminance,
                      parse_hex, to_hex)
from .canvas import Canvas, threshold_map
from .paths import palette_dirs, projects_root, scratch_root
from .sprite import (Sprite, load_grid_dict, load_sprite, output_dir, output_root, project_of,
                     resolve_source)
from .layers import Layer, LayerStack
from .parts import Part, Rig
from .export import (apng, contact_sheet, diff, gif, inspect, onion, palette_swatch, quantize,
                     render, sheet, strip_image, verify_animation)
from .unity import unity_sheet
from .check import check
from . import anim
from .anim import EASINGS, apply_template, keyframes, oscillate, tween
from .importer import depixelize, detect_grid, import_image
from .blueprint import add_blueprint_layer, draw_blueprint, get_blueprint, render_blueprint, save_blueprint
from . import layout, style
from .layout import char_export, char_new, normalize_name, outputs_root, write_index
from .style import game_new, game_palette_add, load_style, validate_style
from .build import build, context

__version__ = "0.1.0"

__all__ = [
    "PixelError", "ColorError", "GridError", "SourceError", "Palette", "generate_ramp",
    "luminance", "parse_hex", "to_hex", "TRANSPARENT", "ROOT", "PALETTE_DIR", "Canvas",
    "threshold_map", "Sprite", "load_sprite", "load_grid_dict", "resolve_source", "output_dir", "output_root",
    "project_of", "projects_root", "scratch_root", "palette_dirs", "Layer", "LayerStack", "Part", "Rig",
    "render", "sheet",
    "gif", "apng", "contact_sheet", "inspect", "onion", "diff", "quantize", "palette_swatch",
    "strip_image", "verify_animation", "new_project", "unity_sheet", "check",
    "anim", "EASINGS", "apply_template", "keyframes", "oscillate", "tween",
    "import_image", "detect_grid", "depixelize", "get_blueprint", "render_blueprint", "save_blueprint",
    "draw_blueprint", "add_blueprint_layer",
    "layout", "style", "normalize_name", "outputs_root", "game_new", "load_style", "validate_style",
    "game_palette_add", "char_new", "char_export", "write_index", "build", "context",
]


def new_project(project, name="sprite", size=(32, 32), palette="pico-8", frames=("idle1",)):
    """Create projects/<project>/<name>.json (blank frames) + notes.md. Returns the sprite."""
    d = projects_root() / project
    d.mkdir(parents=True, exist_ok=True)
    sp = Sprite(size[0], size[1], palette, name=name)
    for f in frames:
        sp.new_frame(f)
    sp.extra["_chars_by_index"] = {}
    path = d / f"{name}.json"
    if path.exists():
        raise PixelError(f"{path} already exists")
    # an empty sprite has no colors; keep a 1-pixel-free valid file with all palette chars unused
    sp.save(path)
    notes = d / "notes.md"
    if not notes.exists():
        notes.write_text(f"# {project}\n\n- {name}.json: {size[0]}x{size[1]}, palette {palette}\n",
                         encoding="utf-8")
    return sp
