"""
UI Annotate Tool
================
Enables BrachyBot's LLM to draw annotations on screenshots.
Supports arrows, circles, rectangles, text labels, and crosshairs.

Flow:
    1. LLM calls ui_annotate(image_url, annotations)
    2. Tool loads the image from disk
    3. Draws annotations using PIL
    4. Saves annotated image to uploads/screenshots/
    5. Returns URL of annotated image
    6. Frontend displays annotated image in chat
"""

import os
import math
import logging
import uuid
from typing import Dict, Any, List
from tool_factory import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Color name to RGB mapping
COLORS = {
    "red": (255, 50, 50),
    "lime": (50, 255, 50),
    "blue": (50, 100, 255),
    "yellow": (255, 255, 50),
    "cyan": (50, 255, 255),
    "magenta": (255, 50, 255),
    "white": (255, 255, 255),
    "orange": (255, 165, 0),
    "green": (0, 180, 0),
    "pink": (255, 150, 200),
}

ANNOTATION_TYPES = ["arrow", "circle", "rect", "text", "crosshair", "line", "ellipse"]


def _get_font(size: int = 16):
    """Get a font for text rendering. Falls back to default if no TTF available."""
    from PIL import ImageFont
    # Try common font paths
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    # Fallback to default
    try:
        return ImageFont.truetype("DejaVuSans-Bold", size)
    except Exception:
        return ImageFont.load_default()


def _draw_arrow(draw, x1, y1, x2, y2, color, width=3):
    """Draw an arrow from (x1,y1) to (x2,y2) with arrowhead."""
    # Line
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)

    # Arrowhead
    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_len = max(15, width * 5)
    arrow_angle = math.pi / 6  # 30 degrees

    ax1 = x2 - arrow_len * math.cos(angle - arrow_angle)
    ay1 = y2 - arrow_len * math.sin(angle - arrow_angle)
    ax2 = x2 - arrow_len * math.cos(angle + arrow_angle)
    ay2 = y2 - arrow_len * math.sin(angle + arrow_angle)

    draw.polygon([(x2, y2), (int(ax1), int(ay1)), (int(ax2), int(ay2))], fill=color)


def _draw_crosshair(draw, cx, cy, color, size=20, width=2):
    """Draw a crosshair at (cx, cy)."""
    draw.line([(cx - size, cy), (cx + size, cy)], fill=color, width=width)
    draw.line([(cx, cy - size), (cx, cy + size)], fill=color, width=width)
    # Small circle at center
    r = 4
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=color, width=width)


def _draw_annotation(draw, annotation: dict, img_width: int, img_height: int):
    """Draw a single annotation on the image."""
    atype = annotation.get("type", "text")
    color_name = annotation.get("color", "red")
    color = COLORS.get(color_name, COLORS["red"])
    label = annotation.get("label", "")
    line_width = annotation.get("width", 3)
    font_size = annotation.get("font_size", 18)
    font = _get_font(font_size)

    if atype == "arrow":
        x1 = annotation.get("x1", 0)
        y1 = annotation.get("y1", 0)
        x2 = annotation.get("x2", 100)
        y2 = annotation.get("y2", 100)
        _draw_arrow(draw, x1, y1, x2, y2, color, line_width)
        # Label at start of arrow
        if label:
            draw.text((x1 + 5, y1 - font_size - 5), label, fill=color, font=font)

    elif atype == "circle":
        cx = annotation.get("cx", 100)
        cy = annotation.get("cy", 100)
        r = annotation.get("r", 50)
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=color, width=line_width)
        if label:
            draw.text((cx + r + 5, cy - font_size // 2), label, fill=color, font=font)

    elif atype == "ellipse":
        cx = annotation.get("cx", 100)
        cy = annotation.get("cy", 100)
        rx = annotation.get("rx", 60)
        ry = annotation.get("ry", 40)
        draw.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)], outline=color, width=line_width)
        if label:
            draw.text((cx + rx + 5, cy - font_size // 2), label, fill=color, font=font)

    elif atype == "rect":
        x1 = annotation.get("x1", 0)
        y1 = annotation.get("y1", 0)
        x2 = annotation.get("x2", 100)
        y2 = annotation.get("y2", 100)
        draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=line_width)
        if label:
            draw.text((x1 + 5, y1 - font_size - 5), label, fill=color, font=font)

    elif atype == "text":
        x = annotation.get("x", 10)
        y = annotation.get("y", 10)
        bg_color = annotation.get("bg_color", None)
        if bg_color:
            bg = COLORS.get(bg_color, (0, 0, 0))
            # Draw background rectangle for text
            bbox = draw.textbbox((x, y), label, font=font)
            pad = 4
            draw.rectangle(
                [(bbox[0] - pad, bbox[1] - pad), (bbox[2] + pad, bbox[3] + pad)],
                fill=bg
            )
        draw.text((x, y), label, fill=color, font=font)

    elif atype == "crosshair":
        cx = annotation.get("cx", 100)
        cy = annotation.get("cy", 100)
        size = annotation.get("size", 25)
        _draw_crosshair(draw, cx, cy, color, size, line_width)
        if label:
            draw.text((cx + size + 5, cy - font_size // 2), label, fill=color, font=font)

    elif atype == "line":
        x1 = annotation.get("x1", 0)
        y1 = annotation.get("y1", 0)
        x2 = annotation.get("x2", 100)
        y2 = annotation.get("y2", 100)
        draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)
        if label:
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            draw.text((mx + 5, my - font_size - 5), label, fill=color, font=font)


class UIAnnotateTool(BaseTool):
    """Draw annotations (arrows, circles, text labels) on screenshots."""

    @property
    def name(self) -> str:
        return "ui_annotate"

    @property
    def description(self) -> str:
        return (
            "Draw annotations on a screenshot image. Supports arrows, circles, "
            "rectangles, text labels, crosshairs, and ellipses. Use this to highlight "
            "specific areas of interest in screenshots before showing them to the user. "
            "Colors: red, lime, blue, yellow, cyan, magenta, white, orange, green, pink."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "URL of the image to annotate (e.g., '/api/screenshots/xxx.png')",
                },
                "annotations": {
                    "type": "array",
                    "description": "List of annotations to draw",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ANNOTATION_TYPES,
                                "description": "Type of annotation",
                            },
                            "x1": {"type": "number", "description": "Start X (arrow, line, rect)"},
                            "y1": {"type": "number", "description": "Start Y (arrow, line, rect)"},
                            "x2": {"type": "number", "description": "End X (arrow, line, rect)"},
                            "y2": {"type": "number", "description": "End Y (arrow, line, rect)"},
                            "cx": {"type": "number", "description": "Center X (circle, crosshair, ellipse)"},
                            "cy": {"type": "number", "description": "Center Y (circle, crosshair, ellipse)"},
                            "r": {"type": "number", "description": "Radius (circle)"},
                            "rx": {"type": "number", "description": "X radius (ellipse)"},
                            "ry": {"type": "number", "description": "Y radius (ellipse)"},
                            "size": {"type": "number", "description": "Size (crosshair)"},
                            "color": {
                                "type": "string",
                                "description": "Color name",
                                "enum": list(COLORS.keys()),
                            },
                            "label": {"type": "string", "description": "Text label to display"},
                            "width": {"type": "integer", "description": "Line width (default 3)"},
                            "font_size": {"type": "integer", "description": "Font size (default 18)"},
                            "x": {"type": "number", "description": "X position (text annotation)"},
                            "y": {"type": "number", "description": "Y position (text annotation)"},
                            "bg_color": {"type": "string", "description": "Background color for text"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["image_url", "annotations"],
        }

    def _execute(self, **kwargs) -> ToolResult:
        from PIL import Image, ImageDraw

        image_url = kwargs.get("image_url", "")
        annotations = kwargs.get("annotations", [])

        if not image_url:
            return ToolResult(success=False, error="image_url is required")
        if not annotations:
            return ToolResult(success=False, error="annotations list is required")

        # Resolve image path from URL
        # URL format: /api/screenshots/filename.png
        if image_url.startswith("/api/screenshots/"):
            filename = image_url.split("/")[-1]
        elif "/" in image_url:
            filename = image_url.split("/")[-1]
        else:
            filename = image_url

        screenshots_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "uploads", "screenshots"
        )
        screenshots_dir = os.path.normpath(screenshots_dir)
        image_path = os.path.join(screenshots_dir, filename)

        if not os.path.exists(image_path):
            return ToolResult(success=False, error=f"Image not found: {image_path}")

        try:
            img = Image.open(image_path).convert("RGBA")
            draw = ImageDraw.Draw(img)
            img_width, img_height = img.size

            # Scale annotations if image was captured at 2x
            # html2canvas scale=2 means annotations might need scaling
            for ann in annotations:
                _draw_annotation(draw, ann, img_width, img_height)

            # Save annotated image
            out_filename = f"annotated_{uuid.uuid4().hex[:12]}.png"
            out_path = os.path.join(screenshots_dir, out_filename)
            img.save(out_path, "PNG")

            out_url = f"/api/screenshots/{out_filename}"
            logger.info(f"Annotated image saved: {out_path}")

            return ToolResult(
                success=True,
                message=f"Annotated image created with {len(annotations)} annotations",
                metadata={
                    "annotated_url": out_url,
                    "original_url": image_url,
                    "annotation_count": len(annotations),
                    "filename": out_filename,
                },
            )
        except Exception as e:
            logger.error(f"Annotation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ToolResult(success=False, error=f"Annotation failed: {str(e)}")
