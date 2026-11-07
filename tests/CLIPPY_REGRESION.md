# Regresión de Clippy y búsqueda

Ejecutar desde la raíz:

```powershell
node --test tests/busqueda_asistida.test.js
node --test tests/interprete_fechas.test.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Las pruebas JavaScript cargan el intérprete y la interfaz de producción en un contexto aislado de Node, con fecha fija y DOM simulado. También comparan el intérprete separado con una copia de las reglas anteriores en `fixtures/interprete_anterior.js`, y lo ejecutan sin DOM. El envío simulado comprueba los parámetros generados, pero no sustituye una prueba de navegador.

La prueba HTTP usa el servidor temporal de `test_csrf`, datos ficticios y una base SQLite separada. Comprueba búsquedas, filtros, papelera, roles, áreas, acceso directo y separación de hábitos; no abre documentos físicos reales.

Siguen necesitando pruebas en un navegador real: posición y legibilidad del bocadillo, tamaño y animaciones, interacción con puntero y teclado, accesibilidad, temporizadores, adaptación a móvil, sonidos, navegación real y comportamiento en caso de recarga o cambios de sesión. El DOM simulado no valida estos aspectos. Los consejos contextuales y tutoriales completos tampoco están cubiertos por las pruebas nuevas.

La copia histórica conserva las reglas anteriores a la Fase 2B. Antes, un año incluido en un oficio activaba un filtro anual y «de enero a marzo» se interpretaba como enero con texto adicional. Ahora el año del oficio queda dentro del oficio; si falta el año de un rango se muestra una advertencia sin aplicar fechas. La comparación histórica se mantiene para los casos cuyo comportamiento no cambió deliberadamente, y las reglas nuevas tienen expectativas propias.

En la Fase 2C las dudas se representan como datos y la interfaz ofrece una aclaración a la vez. Las pruebas cubren selección, omisión, reinicio y conservación de campos editados. Los intervalos incompletos o inválidos requieren editar fechas manualmente; no se intenta inferir información ausente. Para años distintos al actual o anterior se usa igualmente la edición manual. Resolver una duda no ejecuta una búsqueda ni registra un hábito por sí mismo.
