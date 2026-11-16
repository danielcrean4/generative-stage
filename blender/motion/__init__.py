# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
"""Motion families: clips of joint rotations made by scripts, the way art families make meshes.

Plain Python (no Blender) apart from filmstrip.py. Coordinates follow glTF and Godot: Y up,
+Z forward, a character's right is -X. Rotations are Euler angles in radians, applied in
Godot's default YXZ order, so a game can bake them straight into its own animation format.
"""
