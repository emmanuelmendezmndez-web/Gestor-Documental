# Regresión de Clippy y búsqueda

Ejecutar desde la raíz:

```powershell
node --test tests/busqueda_asistida.test.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

Las pruebas JavaScript cargan el archivo de producción en un contexto aislado de Node. Exponen `interpretar` únicamente en la copia en memoria y usan una fecha fija y un DOM simulado. Esta instrumentación depende de la estructura actual del archivo: si cambia, la prueba debe revisarse, no interpretarse automáticamente como un fallo funcional. El envío simulado comprueba los parámetros generados, pero no sustituye una prueba de navegador.

La prueba HTTP usa el servidor temporal de `test_csrf`, datos ficticios y una base SQLite separada. Comprueba búsquedas, filtros, papelera, roles, áreas, acceso directo y separación de hábitos; no abre documentos físicos reales.

Siguen necesitando pruebas en un navegador real: posición y legibilidad del bocadillo, tamaño y animaciones, interacción con puntero y teclado, accesibilidad, temporizadores, adaptación a móvil, sonidos, navegación real y comportamiento en caso de recarga o cambios de sesión. El DOM simulado no valida estos aspectos. Los consejos contextuales y tutoriales completos tampoco están cubiertos por las pruebas nuevas.

Las expectativas recogen el comportamiento actual, incluso interpretaciones ambiguas: un año incluido en un oficio también activa el filtro anual y un rango como «de enero a marzo» se interpreta actualmente como enero con texto adicional. Estas expectativas documentan el estado observado; no certifican que sea el comportamiento deseable.
