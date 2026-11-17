# Clippy Intelligence Engine 1.1

El motor clasifica frases en español de México y devuelve una etiqueta, una candidata, su puntuación, el margen frente a la segunda opción y el motivo de la decisión. Funciona desde la consola o mediante `MotorIntenciones`. El clasificador usa regresión logística de scikit-learn sobre embeddings normalizados de MiniLM. Los pesos de MiniLM permanecen congelados. La salida describe la intención de una frase y carece de conexión con las operaciones de NexusGrid.

El corpus incluye los temas del catálogo de Clippy, los diagnósticos con prefijo `diagnostico_`, la búsqueda documental y la corrección contextual. `desconocido` reúne consultas fuera de alcance, órdenes directas para cambiar datos y expresiones que retiran o niegan una orden. Las preguntas informativas sobre un procedimiento sí pertenecen al tema correspondiente. Los números de registro y demás parámetros de una operación quedan fuera de esta etapa.

## Entrenamiento en PowerShell

Desde la raíz del proyecto, crea un entorno independiente con Python 3.13 y ejecuta lo siguiente.

```powershell
uv venv --python 3.13 .venv-clippy
uv pip install --python .\.venv-clippy\Scripts\python.exe -r requirements-clippy.txt
.\.venv-clippy\Scripts\python.exe entrenar_asistente.py
```

Si existe una copia de MiniLM en `.clippy-modelos/minilm`, se usa directamente. En otro caso, la primera ejecución descarga la [revisión fija de MiniLM](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/tree/e8f8c211226b894fcb81acc59f3b34ba3efd5f42). Las siguientes pueden usar la caché con `--sin-red`. Para una copia de esa misma revisión en otra carpeta, agrega `--minilm-local RUTA`. El entrenamiento guarda `clasificador.json`, `evaluacion.json` y `matriz_confusion.csv` en `.clippy-modelos`. Los coeficientes se guardan como JSON y se leen como datos.

## Prueba manual

```powershell
.\.venv-clippy\Scripts\python.exe clippy_intenciones.py "¿Cuánto disco libre queda?" "Dnd mando msj al equipo" "No publiques nada"
.\.venv-clippy\Scripts\python.exe clippy_intenciones.py
```

El segundo comando abre el laboratorio interactivo y carga el modelo una sola vez. Cada frase se guarda en `.clippy-modelos/laboratorio.json` con fecha UTC, modelo y predicción. Usa **S** para confirmar, **N** para elegir otra intención, **D** para marcarla como desconocida o **Enter** para etiquetarla más tarde. El registro conserva la predicción original junto con tu etiqueta. Las frases pasadas como argumentos imprimen sus resultados en JSON.

`aceptada` significa que la candidata pasó el umbral y el margen mínimo. `fuera_de_alcance` indica que ganó la clase desconocida o que el filtro de alcance rechazó la candidata. `incierta` indica que la puntuación o el margen fueron insuficientes.

## Revisar e incorporar ejemplos del laboratorio

```powershell
.\.venv-clippy\Scripts\python.exe clippy_intenciones.py --revisar
.\.venv-clippy\Scripts\python.exe clippy_intenciones.py --incorporar
```

En la revisión puedes completar etiquetas pendientes. Usa **A** para aprobar un ejemplo, **E** para cambiar su etiqueta, **R** para rechazarlo o **Enter** para pasar al siguiente. Las dos operaciones funcionan sin cargar MiniLM. Solo `--incorporar` escribe en `entrenamiento.json`, y lo hace con las frases aprobadas. El comando omite duplicados, variantes textuales cercanas y coincidencias con los conjuntos reservados. Conserva en el registro el resultado de la incorporación y el motivo de cada omisión. Si usas un archivo de registro distinto con `--registro RUTA`, pasa la misma opción al capturar, revisar e incorporar.

## Volver a entrenar

Agrega ejemplos al JSON de entrenamiento bajo su intención y conserva las frases de calibración y evaluación aparte. Si agregas una intención, agrega ejemplos distintos para esa etiqueta en los tres archivos. Vuelve a ejecutar `entrenar_asistente.py`. Si quieres comparar dos versiones, cambia `--salida` y `--informe` a una carpeta nueva. El CSV se guarda junto al informe.

El entrenamiento valida duplicados con normalización de acentos, mayúsculas y puntuación. También detecta variantes textuales cercanas entre particiones. El informe incluye una auditoría de cercanía por embeddings, las huellas de los corpus, precisión, exhaustividad y F1 por etiqueta, y cada error con su frase y candidata. La matriz usa filas para la intención esperada y columnas para la predicha. El umbral y el margen se seleccionan solo con el conjunto de calibración. La medición de CPU usa un proceso nuevo, tres inferencias de calentamiento y una frase por llamada. La RAM se mide como memoria residente del proceso.

## Evaluación de la fase 1.1

La corrida local usó 418 frases para entrenar, 105 para calibrar y 140 para evaluar, distribuidas en 34 etiquetas. El mayor coseno entre evaluación y las otras particiones fue 0,8622. El informe no detectó duplicados normalizados ni pares de evaluación con coseno igual o superior a 0,90.

| Métrica | Resultado |
|---|---:|
| Exactitud con rechazo | 72,1 % |
| Exactitud de la primera candidata | 73,6 % |
| F1 macro | 0,744 |
| Proporción de frases aceptadas | 80,7 % |
| Acierto entre las aceptadas | 83,2 % |
| Consultas desconocidas rechazadas | 7 de 8 |
| Umbral de puntuación | 0,25 |
| Margen mínimo | 0,08 |

En Windows 11, con cuatro hilos de CPU, la latencia por frase fue de 218 ms en p50 y 922 ms en p95. Cargar el motor tomó 59,1 s. El proceso usó 609 MiB de RAM residente después de la carga y alcanzó 698 MiB de pico. Estas mediciones corresponden a esta máquina y corrida.

Expedientes tuvo un F1 de 0,286 y tres rechazos. Documentos obtuvo 0,333 y Subida 0,400. Una pregunta fuera de alcance sobre el pronóstico del fin de semana se aceptó como corrección contextual. También se confundieron la vinculación de un documento y la creación de un expediente. Cada intención conocida tiene cuatro frases de evaluación, por lo que su F1 individual puede variar mucho con una sola frase.

## Comparación tras ampliar el corpus

La evaluación original se conserva en `datos/clippy/evaluacion.json`. Sirvió para localizar confusiones entre operaciones y orientar las adiciones al corpus. La comparación usa `datos/clippy/evaluacion_optimizada.json`, un conjunto reservado de 131 frases que incluye 22 casos fuera de alcance. Los dos clasificadores reciben las mismas frases y usan los mismos pesos de MiniLM.

El candidato añade un clasificador binario de alcance sobre el mismo embedding. Su umbral se calibra junto con la puntuación mínima y el margen del clasificador multiclase. La selección busca maximizar F1 macro entre los candidatos que rechazan al menos el 90 % de los casos fuera de alcance de calibración. Si ninguno lo consigue, prioriza el mayor rechazo disponible.

Con la línea base preservada en `.clippy-modelos/fase-1.1`, ejecuta la comparación con el entorno local.

```powershell
.\.venv-clippy313\Scripts\python.exe entrenar_asistente.py --sin-red --base .clippy-modelos/fase-1.1/clasificador.json --salida .clippy-modelos/optimizado/clasificador.json --informe .clippy-modelos/optimizado/evaluacion.json
.\.venv-clippy313\Scripts\python.exe clippy_intenciones.py --sin-red --modelo .clippy-modelos/optimizado/clasificador.json "¿Cómo consulto un legajo existente?" "No borres este documento"
```

El informe incluye ambas evaluaciones y sus mediciones independientes. `desconocidas_aceptadas` cuenta las frases fuera de alcance etiquetadas como una intención válida. `errores_hacia_operaciones` registra las clasificaciones incorrectas que terminan en un tema de operación. Una sola frase puede figurar en ambos indicadores.

| Métrica en las 131 frases nuevas | Fase 1.1 | Candidato |
|---|---:|---:|
| Exactitud | 63,4 % | 69,5 % |
| F1 macro | 0,675 | 0,699 |
| Tasa de aceptación | 77,9 % | 70,2 % |
| Acierto entre frases aceptadas | 70,6 % | 77,2 % |
| Fuera de alcance aceptadas | 11 de 22 | 2 de 22 |
| Errores hacia temas de operación | 17 | 13 |
| F1 de Expedientes | 0,250 | 0,769 |
| F1 de Documentos | 0,667 | 0,600 |
| F1 de Subida | 0,222 | 0,222 |

El entrenamiento pasó de 418 a 614 frases y la calibración de 105 a 134. El mayor coseno de una frase de la evaluación nueva con entrenamiento o calibración fue 0,8867. Los umbrales finales fueron 0,30 de puntuación, 0,04 de margen y 0,60 de alcance. Los dos casos fuera de alcance que aún se aceptaron fueron una orden de editar el título de un archivo y otra de crear un expediente, clasificada como vinculación. Subida sigue confundiéndose con la creación de expedientes y Documentos con Descarga.

En la repetición con orden inverso, ambos procesos usaron unos 609 MiB de RAM residente tras cargar y alcanzaron un pico cercano a 703 MiB. La latencia p50 pasó de 99 a 108 ms y la p95 de 135 a 384 ms. La primera corrida dio 126 y 127 ms en p50, y 650 y 203 ms en p95. La variación de p95 entre corridas impide atribuir una diferencia estable al cambio de clasificador. El informe conserva ambas mediciones.
