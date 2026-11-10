"""Validate supplied inputs, without implementing or invoking the renderer."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, size, label, color=False):
    require(isinstance(value, list) and len(value) == size, label + ': shape')
    require(all(number(x) for x in value), label + ': finite numbers required')
    if color:
        require(all(0 <= x <= 1 for x in value), label + ': outside [0,1]')


def matrix(value, label):
    require(isinstance(value, list) and len(value) == 4, label + ': shape')
    for row in value:
        vector(row, 4, label)


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label + ': range/type')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def texture(path):
    obj = load(path)
    integer(obj['width'], 1, 256, str(path))
    integer(obj['height'], 1, 256, str(path))
    require(len(obj['pixels']) == obj['width'] * obj['height'], 'texture pixel count')
    for pixel in obj['pixels']:
        vector(pixel, 4, str(path), color=True)


def validate(path):
    obj = load(path)
    require(type(obj['schema_version']) is int and obj['schema_version'] == 1, 'schema_version')
    integer(obj['width'], 1, 512, 'width')
    integer(obj['height'], 1, 512, 'height')
    vector(obj['clear_color'], 4, 'clear_color', color=True)
    require(obj['clear_color'][3] == 1, 'background alpha')
    for field in ('view', 'projection'):
        matrix(obj['camera'][field], field)
    mesh_ids, material_ids, instance_ids = set(), set(), set()
    triangle_count = 0
    for mesh in obj['meshes']:
        require(isinstance(mesh['id'], str) and mesh['id'] not in mesh_ids, 'mesh id')
        mesh_ids.add(mesh['id'])
        require(len(mesh['positions']) == len(mesh['uvs']), 'vertex/UV counts')
        for pos in mesh['positions']:
            vector(pos, 3, 'position')
        for uv in mesh['uvs']:
            vector(uv, 2, 'UV')
        for indices in mesh['triangles']:
            require(isinstance(indices, list) and len(indices) == 3, 'triangle shape')
            for index in indices:
                integer(index, 0, len(mesh['positions']) - 1, 'vertex index')
        triangle_count += len(mesh['triangles'])
    for material in obj['materials']:
        require(isinstance(material['id'], str) and material['id'] not in material_ids, 'material id')
        material_ids.add(material['id'])
        vector(material['base_color'], 4, 'base_color', color=True)
        require(material['alpha_mode'] in ('OPAQUE', 'MASK', 'BLEND'), 'alpha mode')
        cutoff = material.get('alpha_cutoff', 0.5)
        require(number(cutoff) and 0 <= cutoff <= 1, 'alpha cutoff')
        if 'texture' in material:
            texture((path.parent / material['texture']).resolve())
    for instance in obj['instances']:
        integer(instance['id'], 1, 2**32 - 1, 'instance id')
        require(instance['id'] not in instance_ids, 'duplicate instance id')
        instance_ids.add(instance['id'])
        require(instance['mesh'] in mesh_ids, 'missing mesh reference')
        require(instance['material'] in material_ids, 'missing material reference')
        require(type(instance.get('visible', True)) is bool, 'visible type')
        matrix(instance['model'], 'model')
    return triangle_count, len(instance_ids)


def main():
    import PIL
    require(sys.version_info[:2] == (3, 13), 'Use Python 3.13 for the supplied environment')
    require(PIL.__version__ == '12.3.0', 'Install requirements.txt')
    paths = sorted((ROOT / 'scenes').glob('*.json'))
    require(len(paths) == 7, 'Expected seven supplied scenes')
    for path in paths:
        triangles, instances = validate(path)
        print(f'OK {path.name}: {triangles} mesh triangles, {instances} instances')
    print('Input checks passed. Rendering functionality has not been tested.')


if __name__ == '__main__':
    try:
        main()
    except (KeyError, ValueError, TypeError, OSError, ImportError) as exc:
        raise SystemExit(f'Input check failed: {exc}') from None
