# Licence of the scripts in this folder

Every script in this folder is offered under **MIT OR GPL-3.0-or-later**: you may use, copy and change it under either
licence, at your choice. The MIT text is the repository's [LICENSE](../LICENSE); the GPL text is
[LICENSE-GPL-3.0.txt](LICENSE-GPL-3.0.txt). Each Python file carries the line `SPDX-License-Identifier: MIT OR GPL-3.0-or-later`,
so the choice stays with a file that is copied out of this folder.

Why a second licence: most of these scripts run inside Blender and call its Python API (`bpy`, `bmesh`, `mathutils`).
Blender is released under the GNU General Public License. Whether a script that only calls that API must itself be
under the GPL is a question the Blender project addresses on its licence page, <https://www.blender.org/about/license/>
(and its linked FAQ); read it there, as this note does not restate it. The MIT licence is GPL-compatible, and offering
the GPL as well lets anyone who reads that page as requiring the GPL use the scripts under it without asking. The
scripts here call Blender's API only: none copies code from Blender or from a Blender add-on.

The rest of the repository is under the MIT licence (see [LICENSE](../LICENSE)). Blender itself is a separate program that
you install; this repository does not include or redistribute it. What you make with Blender is yours: the Blender
manual says "The GPL only applies to the Blender application and not the artwork you create with it"
(<https://docs.blender.org/manual/en/latest/getting_started/about/license.html>, checked November 2026).
