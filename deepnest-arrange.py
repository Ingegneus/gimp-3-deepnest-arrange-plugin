#!/usr/bin/env python
# -*- coding: utf-8 -*-

import gi
gi.require_version('Gimp', '3.0')
from gi.repository import Gimp
gi.require_version('GimpUi', '3.0')
from gi.repository import GimpUi
from gi.repository import GObject, GLib, Gtk, Gio, Gegl
import sys, os, re, math
import xml.etree.ElementTree as ET
from svgelements import SVG

def crop_layer_to_content(image, layer):
    procedure = Gimp.get_pdb().lookup_procedure('crop-layer-to-content')
    config = procedure.create_config()
    config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    config.set_property('image', image)
    config.set_core_object_array('drawables', [layer])
    result = procedure.run(config)

def parse_svg(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()
    return root

def get_scale(svg):
    width_sheet = float(svg.attrib["width"].replace("mm","").replace("in",""))
    width_view = svg.attrib["viewBox"].replace("mm","").replace("in","")
    width_view = float(width_view.split(" ")[2])
    scale = width_sheet/width_view
    return scale

def make_new_image(ppm, scale, sheet):
    box = sheet[0]
    sheet_w = float(box.attrib["width"]) * scale * ppm
    sheet_h = float(box.attrib["height"]) * scale * ppm
    img = Gimp.Image.new(sheet_w, sheet_h, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(img, "bg", sheet_w, sheet_h, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
    img.insert_layer(layer, None, -1)
    Gimp.Display.new(img)
    return img

def get_transform(transform_string, id, deepnest_svg_elements):
    this_element = deepnest_svg_elements.get_element_by_id(id)
    x1, y1, x2, y2 = this_element.bbox()
    x = x1 + (x2 - x1)/2
    y = y1 + (y2 - y1)/2

    rot = 0 
    match = re.search(r"rotate\(\s*([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*\)", transform_string)
    if match:
        rot = float(match.group(1))
    print("x: " + str(x) + " y: " + str(y) + " rot: " + str(rot))
    return x, y, rot

def draw_bb(scale, ppm, image, id, deepnest_svg_elements):
    this_element = deepnest_svg_elements.get_element_by_id(id)
    x1,y1,x2,y2 = this_element.bbox()

    image.select_rectangle(Gimp.ChannelOps.REPLACE, x1 *scale*ppm, y1*scale*ppm, (x2-x1)*scale*ppm, (y2-y1)*scale*ppm)
    image.get_layer_by_name("bg").edit_stroke_selection()
    return

def move_layer_to_zero(layer, image):
    ret, original_x, original_y = layer.get_offsets()

    offset_x = original_x + (layer.get_width() / 2)
    offset_y = original_y + (layer.get_height() / 2)
    
    layer.transform_translate(-offset_x, -offset_y)

def move_layer_to_center(layer, image):
    offset_x = image.get_width()/2-(layer.get_width() / 2)
    offset_y = image.get_height()/2-(layer.get_height() / 2)
    
    layer.transform_translate(offset_x, offset_y)

def deepnest_arrange(procedure, run_mode, image, drawables, config, run_data):

    GimpUi.init("deepnest_arrange")  
    dialog = GimpUi.ProcedureDialog.new(procedure, config, "Configure Plugin") 
    dialog.fill(["dir", "ext", "ppi"])

    if not dialog.run():
        dialog.destroy()
        return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
    dialog.destroy()

    dir = config.get_property("dir")
    ppi = config.get_property("ppi")
    ppm = ppi/25.4 # pixels per mm
    ext = config.get_property("ext").replace(".","")

    deepnest_svg_path = os.path.join(dir, "output.svg")
    deepnest_svg_xml = parse_svg(deepnest_svg_path)
    deepnest_svg_elements = SVG.parse(source=deepnest_svg_path, 
                                      ppi=72)

    scale = get_scale(deepnest_svg_xml)
    print("#########################")
    print(scale)

    sheet_offset = 0.0
    for sheet in deepnest_svg_xml:
        new_image = make_new_image(ppm, scale, sheet)
        i = 0
        for element in sheet:
            if "rect" in element.tag:
                continue

            transform_element_name = element.attrib["id"]
            element_name = element[0].attrib["id"] #the child of element contains the name (aka id) if the image
            element_name = element_name.replace("." + ext, "")
            print(element_name)
            transform_string = element.attrib["transform"]
            center_offset_x, center_offset_y, rot = get_transform(transform_string, 
                                                                transform_element_name, 
                                                                deepnest_svg_elements)

            element_file = Gio.file_new_for_path(os.path.join(dir, element_name + "." + ext))
            element_layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, new_image, element_file)
            new_image.insert_layer(element_layer, None, -1)

            move_layer_to_center(element_layer, new_image)
            element_layer.transform_rotate(math.radians(rot), True, 0, 0)
            crop_layer_to_content(new_image, element_layer)
            
            move_layer_to_zero(element_layer, new_image)
            element_layer.transform_translate(center_offset_x * scale * ppm, (center_offset_y - sheet_offset) * scale * ppm)

            i = i + 1
            if i == 30:
                return

        sheet_offset += float(sheet[0].attrib["height"])

    print("#########################")

    Gimp.displays_flush()
    GLib.free()
    return


class DeepnestArrangePlugIn(Gimp.PlugIn):

    def do_query_procedures(self):
        return ["deepnest-arrange"]

    def do_create_procedure(self, name):
        if name != "deepnest-arrange":
            return None

        procedure = Gimp.ImageProcedure.new(self, 
                                            name,
                                            Gimp.PDBProcType.PLUGIN,
                                            deepnest_arrange, 
                                            None)

        procedure.set_image_types("RGB*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
        procedure.set_menu_label("Deepnest arrange")
        procedure.set_attribution("Ingegneus", "Ingegneus", "2025")
        procedure.add_menu_path("<Image>/Image")
        procedure.set_documentation(
            "Arrange layers using Deepnest",
            "Arrange layers using Deepnest",
            None)

        procedure.add_file_argument("dir", "Directory", "The directory where the images and deepnest output svg reside.", Gimp.FileChooserAction.SELECT_FOLDER, False, None, GObject.ParamFlags.READWRITE)
        procedure.add_string_argument("ext", "File extension", "The filetype of your images", "png", GObject.ParamFlags.READWRITE)
        procedure.add_double_argument("ppi", "Resolution", "The resolution to use for the created file.", 0.1, 9999, 600, GObject.ParamFlags.READWRITE)
        
        return procedure

    
# Plugin entry point
Gimp.main(DeepnestArrangePlugIn.__gtype__, sys.argv)
