<!-- Copyright (c) 2026 Emanuele Torrisi. See LICENSE for applicable terms. -->

<p align="center"><img src="../../logo.png" alt="Verboisy" width="220" /></p>

<p align="center">
  <a href="../../README.md">English</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.ko.md">한국어</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<h1 align="center">Verboisy</h1>
**De una pregunta de investigación a un conjunto de datos con fuentes verificables.**

Investigación con evidencias · Extracción estructurada · Datos locales · Procedencia portable

## El producto

Verboisy es un motor de investigación y extracción para quienes necesitan información estructurada y quieren comprobar su origen. Una pregunta, un esquema y las fuentes permitidas definen el trabajo. El sistema captura observaciones, verifica registros propuestos y conserva evidencias y transformaciones. La CLI y la API Python permiten procesos repetibles y la reanudación del trabajo guardado.

También prepara conjuntos locales o HTTP declarados con adaptadores deterministas, sin llamadas a modelos, búsqueda o navegador. Un flujo separado utiliza un registro en disco y buffers limitados para archivos locales grandes.

**Código consultable, uso con licencia independiente.** [LICENSE](../../LICENSE) permite inspeccionar el código, no ejecutarlo. Pruebas, modificaciones y despliegue requieren un acuerdo escrito separado. Los ejemplos describen uso autorizado.

## Por qué importa este enfoque

Un JSON o una tabla no explican por sí mismos si un hecho fue observado ni cómo se obtuvo un valor. Verboisy incorpora estas comprobaciones al proceso:

- **Evidencia antes de aceptar:** los candidatos del modelo requieren fuentes observadas y verificación determinista; la revisión semántica es independiente.
- **Requisitos controlables:** JSON Schema, identidad, alcance de fuentes y comparabilidad definen resultados admisibles.
- **Trabajo recuperable:** capturas inmutables, puntos de control y diarios de solicitudes conservan progreso y gasto.
- **Transformaciones explicables:** unidades, proyecciones, presentación y agrupaciones conservan vínculos con valores originales y registros contribuyentes.
- **Decisiones explícitas:** una propuesta pausa el trabajo antes de sustituir pregunta o esquema.

Los usos incluyen análisis, datos de referencia, preparación de datasets, sistemas internos e investigaciones reproducibles. Los usos científicos o regulados requieren revisión independiente de fuentes, muestreo y conclusiones. La ambición es convertirse en un estándar fiable de extracción con evidencias, no afirmar un liderazgo ya alcanzado.

## Flujos y formatos

La investigación web usa navegador y modelos configurados, con descubrimiento mediante búsqueda opcional. La preparación determinista lee archivos autorizados o fuentes HTTP GET declaradas. El streaming separado produce contadores, páginas de registros y puntos de control.

| Entrada | Interpretación |
| --- | --- |
| CSV / TSV | Campos de texto exactos, cabeceras explícitas y comprobación de anchura de filas |
| JSON / JSONL | Objetos tipados con decodificación estricta |
| Texto | Registros de texto con ubicación en la fuente |
| DOCX / XLSX | Adaptadores limitados y documentados; no ejecutan macros ni fórmulas |
| Imágenes, vídeos y otros archivos | Captura inmutable de bytes, hashes y referencias; sin interpretación automática |
| Series temporales | Reglas explícitas de series y marcas de tiempo, ordenación y diagnóstico de huecos y duplicados |

Capturar binarios no significa OCR ni interpretación universal de documentos. OAuth, controladores de bases de datos, conectores y paginación de API necesitan integraciones específicas. Véanse los [formatos](../../docs/formats.md).

## Instalación y configuración

Se necesitan Python **3.11–3.14**, Poetry y autorización escrita para ejecutar el software. La CI cubre Linux, macOS y Windows. La investigación con modelos requiere un perfil compatible y credenciales; el navegador requiere Chromium y bibliotecas del sistema. Los archivos locales necesitan directorios autorizados y espacio de disco. La instalación normal no requiere compilador C++.

```bash
poetry install
poetry run verboisy --help
```

Guardar claves en un entorno privado o `.env`, a partir de [.env.example](../../.env.example). No publicarlas. Los ejemplos shell usan POSIX; en Windows, configurar las variables mediante el método equivalente.

```bash
poetry run verboisy setup
poetry run verboisy model-config
```

`model-config` muestra configuración y presencia de credenciales, no sus valores. La preparación local determinista no necesita modelos ni navegador. Véanse [proveedores](../../docs/providers.md) y [validación](../../docs/validation.md).

## Investigación web y API

```bash
poetry run verboisy run \
  --goal "Find research institutions and their explicitly published homepages" \
  --schema '[name,website,country]' \
  --export institutions.json
```

El descubrimiento automático requiere un proveedor de búsqueda; un task puede declarar URL iniciales. JSON Schema permite tipos y restricciones precisos. Los datos ausentes pueden permanecer `null`; los valores sin respaldo se rechazan. Aceptar resultados no certifica cobertura exhaustiva de la web.

```python
from verboisy import run

result = run(
    goal="Find research institutions and their published homepages",
    schema=["name", "website", "country"],
    export="institutions.json",
)
print(result.run_id, result.status, result.records)
```

Las aplicaciones asíncronas usan `arun`. La API habitual materializa los registros aceptados; las entradas locales grandes usan streaming.

## Datos locales e internos

```bash
export DATASET_LOCAL_ROOTS='["/srv/verboisy-inputs"]'
poetry run verboisy run \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.json
```

El directorio y el esquema deben existir. Las credenciales de un modelo no conceden acceso al sistema de archivos. Las fuentes HTTP declaradas usan descargas limitadas, control de redirecciones, DNS fijado y secretos asociados al origen. La ubicación de fuentes y la ejecución del modelo son independientes: un modelo remoto puede recibir observaciones. Revisar transferencias, registros, red y retención antes de usar datos confidenciales.

## Grandes conjuntos de datos

```bash
poetry run verboisy stream \
  --database observations-stream.db \
  --dataset-file 'jsonl=/srv/verboisy-inputs/observations.jsonl' \
  --schema observation-schema.json \
  --export observations.jsonl
```

El registro streaming conserva bloques inmutables y progreso transaccional. `stream-status` lista trabajos; `stream --resume JOB_ID` reanuda uno guardado. `StreamLedger` ofrece lectura por páginas.

Una carga JSONL medida en Linux/Python 3.12 preparó y exportó **1.000.000 de filas** desde **1.105.888.890 bytes**, con **89,15 MiB** de RSS máximo y **130,81 s** de duración. Se verificaron integridad del export y recuperación tras borrar la fuente original. Es una medición concreta, no una garantía general. Véanse [streaming](../../docs/streaming.md) y [benchmarks](../../docs/benchmarks.md).

## Propuestas, reanudación y evidencias

```bash
poetry run verboisy changes --run-id RUN_ID
poetry run verboisy status --run-id RUN_ID
poetry run verboisy run --resume RUN_ID
```

`--resume` conserva los requisitos y rechaza la propuesta; `--okresume` acepta exactamente los cambios guardados. Las propuestas pueden cambiar tipos, columnas o alcance de búsqueda. Reanudar no reinicia el gasto ni autoriza otras fuentes implícitamente.

Los intervalos siguen siendo intervalos: un límite inferior no se convierte en valor exacto o máximo inventado. Columnas numéricas min/max requieren un esquema apropiado. Los valores de presentación predeterminados son kilogramos, metros y día/mes/año; las alternativas explícitas conservan las evidencias originales. Los diagnósticos temporales no interpolan datos ni adivinan horas locales ambiguas.

Los exports portables incluyen evidencias, eventos relevantes, procedencia y fuentes capturadas cuando corresponde. Las agrupaciones identifican sus contribuyentes. Las sumas de comprobación establecen consistencia de bytes con el manifiesto, no verdad ni autenticidad independiente. Véase [procedencia](../../docs/proof.md).

## Arquitectura y documentación

Python gestiona orquestación, contratos, adaptadores, CLI y registros SQLite. Componentes C++17 opcionales aceleran ciertos cotejos de evidencias con implementaciones Python de referencia. Tests y CI comprueban plataformas, navegador, recuperación e integridad; se exige cobertura completa de instrucciones y ramas. La calidad real y la compatibilidad de proveedores requieren evaluaciones propias.

[CLI](../../docs/cli.md) · [API](../../docs/api.md) · [Contratos](../../docs/contracts.md) · [Identidad](../../docs/smartid.md) · [Ingestión](../../docs/ingestion.md) · [Presentación](../../docs/presentation.md) · [Semántica](../../docs/research-semantics.md) · [Arquitectura](../../ARCHITECTURE.md) · [Versiones](../../CHANGELOG.md)

## Licencias, demos y consultas comerciales

Verboisy es software propietario, **no open source**. La licencia inglesa es la autoridad; esta traducción no altera permisos. Identificador: `LicenseRef-Verboisy-Source-Inspection-1.0`. Los componentes de terceros conservan sus licencias. Ejecución, pruebas, modificación, integración, distribución y hosting requieren permisos escritos separados.

Contactar con **[emanueletorrisi98@gmail.com](mailto:emanueletorrisi98@gmail.com)** para demos, evaluaciones, licencias internas o enterprise, inversiones, asociaciones o posible colaboración remunerada. Describir flujo, fuentes, volumen y entorno; no enviar secretos ni datos confidenciales. Precios, soporte y derechos se acuerdan individualmente. Véanse [licencias](../../docs/licensing.md) y [consultas comerciales](../../docs/commercial.md).

## Comentarios y colaboración

**Emanuele Torrisi** crea y mantiene Verboisy y es actualmente su único desarrollador. [Informes de errores y solicitudes de funciones](https://github.com/EmanueleTorrisi/verboisy/issues) son bienvenidos. Las vulnerabilidades se comunican en privado según la [política de seguridad](../SECURITY.md).

No se aceptan contribuciones de código no solicitadas. La colaboración remunerada requiere acuerdos previos sobre alcance, compensación, confidencialidad y propiedad intelectual. Los cambios se registran en el [changelog](../../CHANGELOG.md); el [historial](../../docs/development-roadmap.md) describe la evolución de 0.1.0 a 1.0.0. Consulta [participación](../CONTRIBUTING.md) y [derechos](../../COPYRIGHT.md).
## Ejemplos de flujos

[Research catalogue](../../examples/research_catalog/README.md) ·
[Large local observation pipeline](../../examples/streaming_observations/README.md) ·
[Version history: 0.1.0–1.0.0](../../docs/development-roadmap.md)
