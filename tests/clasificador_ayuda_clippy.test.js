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
