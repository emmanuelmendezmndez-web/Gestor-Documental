const {test} = require('node:test');
const assert = require('node:assert/strict');
const clasificar = require('../app/static/clasificador_ayuda_clippy.js');

test('búsquedas documentales no dependen de palabras aisladas', () => {
    for (const texto of ['Busca contratos de 2025', 'Contratos de 2025', 'documento subir papelera', 'contratos sobre como subir precios', '¿Contratos de 2025?']) assert.deepEqual(clasificar(texto), {tipo:'busqueda_documental'}, texto);
});
test('correcciones 3B tienen prioridad incluso con contexto vacío', () => {
    for (const texto of ['Mejor de abril', 'Quita Tesorería', 'quitar tesoreria', 'Olvida los filtros', 'Empieza de nuevo', 'Conserva la categoría']) assert.deepEqual(clasificar(texto), {tipo:'correccion_contextual'}, texto);
});
test('preguntas explícitas identifican los temas del catálogo', () => {
    const ejemplos = [
        ['Cómo uso la biblioteca','biblioteca'], ['¿Cómo busco contratos?','busqueda'],
        ['¿Cómo subo un documento?','subida'], ['COMO consulto EXPEDIENTES','expedientes'],
        ['Cómo crear un expediente','gestionar_expedientes'], ['¿Cómo vincular documentos al expediente?','vincular_documentos'],
        ['Cómo funciona la papelera','papelera'], ['¿Cómo recupero un documento eliminado de la papelera?','restaurar'],
        ['Cómo eliminar definitivamente un documento','eliminar_definitivamente'], ['¿Cómo gestiono usuarios?','usuarios'],
        ['¿Por qué no puedo eliminar?','permisos']
    ];
    for (const [texto, tema] of ejemplos) assert.deepEqual(clasificar(texto), {tipo:'ayuda', tema}, texto);
});
test('solicita aclaración para múltiples temas o intención poco clara', () => {
    assert.equal(clasificar('Cómo subir y buscar documentos').tipo, 'aclaracion');
    assert.deepEqual(clasificar('¿Cómo?'), {tipo:'aclaracion', motivo:'intencion_ambigua', alternativas:['ayuda','busqueda']});
    assert.equal(clasificar('').motivo, 'entrada_vacia');
});
test('clasificación no modifica estado ni aplica propuestas', () => {
    const ctx = {estado:{filtros:{categoria:'Contratos', departamento:'Tesorería'}, manuales:['departamento']}, areas:['Tesorería'], categorias:['Contratos']};
    const antes = structuredClone(ctx);
    assert.equal(clasificar('Quita Tesorería', ctx).tipo, 'correccion_contextual');
    assert.deepEqual(ctx, antes);
});

test('reconoce formas alternativas de pedir orientación sobre cada módulo', () => {
    for (const [texto, tema] of [
        ['Explícame los indicadores del panel principal', 'inicio'],
        ['¿Cómo veo la vista previa?', 'documentos'],
        ['¿Dónde descargo el archivo?', 'descargar'],
        ['¿Cómo cambio el tema a modo oscuro?', 'ajustes'],
        ['¿Cómo funciona el chat?', 'mensajeria'],
        ['¿Dónde veo los comunicados?', 'avisos'],
        ['¿Cómo cambio la duración de un aviso?', 'gestionar_avisos'],
        ['¿Dónde reviso el registro de operaciones?', 'actividad'],
        ['¿Qué hago si caducó la sesión?', 'sesion'],
        ['¿Dónde se muestra el almacenamiento?', 'almacenamiento'],
        ['Me sale formato no permitido al cargar el documento', 'formato_subida'],
        ['¿Cuánto puede pesar el archivo?', 'limite_subida'],
    ]) assert.deepEqual(clasificar(texto), {tipo:'ayuda', tema}, texto);
});

test('separa comprobaciones de ayuda, búsquedas y cambios en el diálogo', () => {
    for (const [texto, tema, extra] of [
        ['¿Está operativo el servidor?', 'sistema', {}],
        ['Mensajería no carga', 'mensajeria', {}],
        ['¿Cuánto espacio queda en disco?', 'almacenamiento', {}],
        ['¿Tengo permiso para subir documentos?', 'permisos', {accion:'subir'}],
        ['¿Por qué no puedo descargar el documento 123?', 'documento', {registro:'123'}],
        ['No encuentro el documento', 'documento', {registro:undefined}],
    ]) assert.deepEqual(clasificar(texto), {tipo:'diagnostico', tema, ...extra}, texto);
    assert.equal(clasificar('Comunicados de 2025').tipo, 'busqueda_documental');
    assert.equal(clasificar('Quita el filtro de fecha').tipo, 'correccion_contextual');
});
