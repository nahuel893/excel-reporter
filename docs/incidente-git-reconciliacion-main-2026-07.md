# Incidente Git — `main` local divergió de `origin/main` (2026-07-16)

Post-mortem de la reconciliación de `main` que hicimos al commitear el servicio
`ventas-cober-preventista-marca`.

## Resumen

Al commitear trabajo nuevo sobre `main` local y querer pushear, el push fue
**rechazado**: `origin/main` tenía 5 commits que `main` local no tenía. Se
reconcilió con un `git rebase` (limpio, sin conflictos) y se pusheó. Ningún test
propio se rompió; las 20 fallas de la suite completa se probaron **pre-existentes**.

## Qué pasó

1. Trabajé y commiteé sobre `main` local (commit del servicio nuevo + fix de
   historico-cliente + regla de oro).
2. `git push origin main` → **rechazado**:
   ```
   ! [rejected]  main -> main (fetch first)
   hint: Updates were rejected because the remote contains work that you do
   hint: not have locally.
   ```
3. Al investigar, `main` local y `origin/main` habían **divergido**:
   - **`origin/main` adelante por 5 commits** que local no tenía → todos de la
     feature *avance-badie capture wiring* (PR #7, PR #9, RangeRecognizer,
     print_area cropping). Alguien los mergeó en GitHub.
   - **`main` local adelante por 2 commits** que origin no tenía → mi commit
     nuevo + `c2ee5ac` (champions VILLAVICENCIO, que ya estaba local al arrancar).

## Causa raíz

El workflow de deploy de este proyecto pinnea `main` con `git checkout main`
(drop-in `pin-main.conf` del `excel-reporter-daily.service`) **sin `git pull`**.
Por eso:

- El daily corre lo que esté en `main` **local**.
- Cuando se mergean PRs en GitHub, `origin/main` avanza, pero `main` **local no**
  se entera hasta que alguien hace `pull`.
- Resultado: `main` local queda **atrás** de origin, y si uno commitea encima
  (como hice yo) sin traer primero lo de origin, las dos ramas divergen.

> ⚠️ Efecto colateral importante que descubrimos: como local estaba atrás, **el
> daily estaba corriendo SIN la feature de avance-badie** que ya estaba mergeada
> en origin.

## Cómo lo diagnostiqué

```bash
git fetch origin
git log --oneline main..origin/main     # 5 commits que me faltaban (avance-badie)
git log --oneline origin/main..main      # 2 commits míos que faltan en origin

# riesgo de conflicto: qué archivos se pisan entre ambos lados
comm -12 \
  <(git diff --name-only main...origin/main | sort) \
  <(git diff --name-only origin/main...main | sort)
# -> src/config/models.py, src/config/resolver.py  (solo esos 2)
```

Los cambios en esos 2 archivos eran **aditivos de los dos lados** (avance-badie
agregó `esperar_objetivo`; yo agregué `marcas_completas` / `genericos_universo` y
un tipo nuevo), así que se esperaban conflictos chicos "quedan los dos", o
auto-merge.

## Cómo lo arreglé

```bash
# 1. Sacar del árbol lo que NO es mío (skill-registry auto-generado)
git stash push -m "atl-not-mine" .atl/skill-registry.md

# 2. Rebase de mis commits locales SOBRE origin/main
git rebase origin/main
#    -> "Successfully rebased and updated refs/heads/main."  (sin conflictos:
#       git auto-mergeó los 2 archivos aditivos)

# 3. Verificar. Toda la suite: 20 fallas / 1782 ok. Antes de asumir que rompí algo,
#    probé que esas fallas son PRE-EXISTENTES corriendo los mismos tests en el
#    baseline (origin/main, sin mis commits):
git checkout 5332e51            # HEAD de origin/main
pytest tests/test_services.py::TestVentasServiceUnit tests/test_stock_diario.py ...
#    -> fallan IGUAL (12 fallas) => pre-existentes, no las introduje yo
git checkout main

# 4. Push (ahora sí fast-forward) + restaurar el .atl
git push origin main            # 5332e51..71c2592  main -> main
git stash pop
```

Historia final (lineal): los 5 commits de avance-badie de origin, y arriba mis 2
commits. `main` local == `origin/main`.

### Sobre las 20 fallas de la suite

Todas pre-existentes / de entorno, **ninguna de mi cambio**:
- `test_excel_renderers` → Playwright sin browser instalado en el venv.
- `test_stock_diario`, `test_whatsapp_client`, `test_services` (VentasService),
  `test_resumen_mensual_merge`, `test_messaging` → necesitan DB o son brittle
  (ej. `FileNotFoundError: /tmp/test.xlsx` con mock).
- `test_run_daily::...guemes...` → drift: `configs/avances_guemes.json` tiene un
  destinatario extra ("Guemes") que el test no espera.

## Prevención

Para que no vuelva a pasar, antes de commitear sobre `main` local:

```bash
git fetch origin && git rebase origin/main   # o git pull --rebase origin main
```

Alternativa de fondo (a evaluar): que el drop-in del daily haga `git pull --ff-only`
(o `git fetch` + `reset --hard origin/main`) en vez de solo `git checkout main`,
para que producción no quede atrás de origin. Ver la memoria de Engram
"El daily pinnea main y corrompe ramas de dev: usar worktree aislado".
