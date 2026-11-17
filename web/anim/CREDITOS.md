# Animaciones grabadas

`clips.json` sale de dos fuentes.

## Quaternius: Universal Animation Library 1 y 2

Todos los clips sin prefijo de estilo (`idle`, `talk`, `walk`, `crouch`, `jump_land`, `fold_arms`…). Versiones
«Standard» de OpenGameArt (https://quaternius.com):

- https://opengameart.org/content/universal-animation-library
- https://opengameart.org/content/universal-animation-library-2

Licencia: **CC0 1.0** (dominio público, https://creativecommons.org/publicdomain/zero/1.0/). Se pueden incluir y
modificar sin pedir permiso; se cita igualmente al autor.

## The 100STYLE Dataset - Ian Mason

Los clips `walk_<estilo>` e `idle_<estilo>` (andar y estar de pie con distintos estilos: neutro, alegre, triste,
enfado, tímido, orgullo, pensar, ligero, nervioso). Captura de movimiento XSens de Ian Mason, Sebastian Starke y
Taku Komura:

- https://ianxmason.github.io/100style
- https://zenodo.org/record/8127870 (`100STYLE.zip`)

Licencia: **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/). Atribución: «The 100STYLE Dataset - Ian
Mason». Cambios hechos: se recortó un bucle de cada toma (`<Estilo>_FW.bvh` y `<Estilo>_ID.bvh`), se quitó el
recorrido y el giro por la sala, se enderezó un poco el cuello (15°) y se pasó al esqueleto de VRM.

## Cómo se rehace

Se convirtieron al esqueleto normalizado de VRM 1.0 con `scripts/convertir_animaciones.py` (los BVH los lee
`scripts/anim_bvh.py`), el 17 nov 2026. Los paquetes originales no van en el proyecto: se bajan los dos .zip de
Quaternius y `100STYLE.zip`, y se pasan al script el .glb de cada uno de Quaternius
(`Godot/AnimationLibrary_Godot_Standard.glb` y `Unreal-Godot/UAL2_Standard.glb`) y, con `--estilos`, la carpeta
`100STYLE` descomprimida (basta con las carpetas de los estilos de `STYLES`).
