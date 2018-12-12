from xml.etree import ElementTree as ET
import re
import sys


input_xml = ET.ElementTree(file=sys.argv[1])
for class_ in input_xml.findall(".//class"):
    filename = (class_.get("filename"))
    filename = re.sub(".tox/.*/site-packages/", "src/", filename)
    filename = re.sub("_sync", "_async", filename)
    class_.set("filename", filename)
input_xml.write(sys.argv[1], xml_declaration=True)
