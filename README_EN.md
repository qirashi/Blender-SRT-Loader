# Blender-SRT-Loader [[RU](./README.md) | EN]
An independent Blender add-on that provides support for importing .srt files. This format is part of SpeedTree® technology and appears in games based on the BigWorld engine. The add-on is created solely for compatibility purposes and is not affiliated with IDV or any other rights holders.

> [!WARNING]
> 
> The plugin is provided “as is”, without any warranties. The author assumes no responsibility for any damage arising from its use. You must comply with the EULA of the products from which the imported files originate, and you use the plugin at your own risk.

## Features
- Import of geometry from `.srt` version 06.0.0.
- Automatic material creation with main textures (`.dds`).
- Grouping by level of detail (LOD) into collections.
- Correct UVs and custom normals.

## Installation
1. Download the repository ZIP archive.
2. In Blender: `Edit → Preferences → Add-ons → Install…`, select the archive.
3. Enable the add-on “Import-Export: SRT Loader (.srt)”.

## Usage
- Menu `File → Import → SpeedTree SRT (.srt)`.
- Choose an `.srt` file.
- After import, collections appear in the scene: `<name>_SRT` and nested `<name>_LOD0`, `<name>_LOD1`…
- Textures are searched for in the folder of the imported file.