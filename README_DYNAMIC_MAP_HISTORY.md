# La evolución del sistema de despacho en el testbed Plug-and-Plan: de orden manual a mapas dinámicos

## Resumen ejecutivo para lector externo

Este documento cuenta cómo evolucionó la lógica de producción del testbed físico Plug-and-Plan. El problema no es solo "qué pieza entra primero", sino **qué decisión debe tomar cada robot cuando tiene varias acciones físicamente posibles al mismo tiempo**. La aportación principal es pasar de reglas de prioridad fijas a un **mapa de despacho precomputado, protegido por sensores y timeouts**, que permite que cada decisión crítica pueda ser distinta según el estado previsto de la corrida.

La idea final no es controlar el robot con IA en vivo ni reoptimizar durante la ejecución. El mapa se calcula antes de pulsar `Confirm & Apply`, se guarda para esa composición concreta, y durante la corrida real el sistema intenta seguirlo solo si la acción es físicamente segura: si falta una pieza, una estación no terminó, un sensor no coincide o aparece una condición inesperada, el sistema espera un margen acotado y luego vuelve a la política reactiva segura.

En hardware real, las corridas validadas muestran reducciones de makespan de **12.0% a 18.3%** en los casos donde existe congestión real, y un caso de control con mejora nula confirma que el método no inventa ahorro cuando no hay nada que optimizar.

## Cómo leer el sistema físico

El flujo puede entenderse como una célula con cuatro manipuladores y varias estaciones:

- **xArm2** alimenta piezas desde el stack inicial hacia el sistema.
- **xArm1** mueve piezas desde C1S2 hacia el láser o directamente hacia C2S1.
- **robot2** clasifica piezas desde C2S2 hacia Bantam, C4, IBS o scrap.
- **robot1** descarga las salidas finales desde C3 y C4.
- **Rojo** suele implicar ruta de láser, **azul** suele implicar ruta de Bantam, y **verde** usa la ruta directa hacia C3.

Tres términos importan para toda la presentación:

- **Makespan**: tiempo total desde que xArm2 empieza a coger la primera pieza hasta que robot1 vuelve a home tras colocar la última.
- **Fixed optimizado**: el mejor orden inicial encontrado por simulación, pero manteniendo las prioridades internas fijas de los robots.
- **Mapa dinámico**: orden inicial más decisiones de despacho calculadas offline; no cambia durante la ejecución, pero está protegido contra desviaciones físicas.

## Regla transversal: las condiciones físicas mandan antes que cualquier política

Esto es importante para no presentar el sistema como si el mapa dinámico "controlara robots" directamente. No lo hace. Y tampoco lo hacía la política fija. En todos los modos —manual, fixed optimizado, mapa de prioridades fijas o mapa dinámico— hay una separación estricta:

```text
politica / mapa / optimizador propone una intencion
        ↓
Factory Supervisor comprueba el estado fisico real
        ↓
si la accion es fisicamente valida, se envia al vendor supervisor
        ↓
si no es valida, se espera un margen acotado o se usa fallback reactivo
```

La política decide **entre acciones posibles**; no puede convertir una acción imposible en válida. Por ejemplo, aunque una regla fija o un mapa precomputado "quiera" descargar Bantam, robot2 no puede hacerlo si C4 está ocupado o Bantam no ha terminado. Aunque el mapa "quiera" que xArm1 retire el láser, xArm1 no puede hacerlo si el láser no está `FINISHED` o C2S1 no está libre. Aunque el orden inicial pida alimentar una pieza verde, xArm2 no puede depositarla en C3 si C3 está ocupado.

Las condiciones físicas mínimas que disparan acciones son:

| Equipo | Acción típica | Condiciones físicas necesarias antes de disparar |
|---|---|---|
| **xArm2** | `INITIAL_STACK -> C1S1` | xArm2 libre, pieza localizada por global vision, pieza no verde, C1S1 libre, vendor uFactory libre. |
| **xArm2** | `INITIAL_STACK -> C3` | xArm2 libre, pieza localizada por global vision, pieza verde, C3 libre, vendor uFactory libre. |
| **Conveyor1** | `C1S1 -> C1S2` | C1S1 ocupado, C1S2 libre, conveyor1 parado, vendor Niryo libre. |
| **xArm1** | `C1S2 -> LASER` | xArm1 libre, C1S2 ocupado, pieza roja esperada, láser libre. |
| **xArm1** | `C1S2 -> C2S1` | xArm1 libre, C1S2 ocupado, pieza no roja esperada, C2S1 libre. |
| **xArm1** | `LASER -> C2S1` | xArm1 libre, láser terminado, C2S1 libre. |
| **Conveyor2** | `C2S1 -> C2S2` | C2S1 ocupado, C2S2 físicamente libre, conveyor2 parado, vendor Niryo libre. |
| **robot2** | `C2S2 -> C4/Bantam/IBS/Scrap` | robot2 libre, C2S2 ocupado, C4 libre para iniciar clasificación, visión local disponible; la ruta final depende del color detectado y del estado de Bantam. |
| **robot2** | `Bantam -> C4` | robot2 libre, Bantam terminado con pieza pendiente, C4 libre. |
| **robot1** | `C3 -> final` | robot1 libre, C3 ocupado, pieza asentada tras el depósito, vacuum disponible. |
| **robot1** | `C4 -> final` | robot1 libre, C4 ocupado, pieza asentada tras el depósito, vacuum disponible. |

Por eso la contribución del mapa dinámico no es saltarse seguridad ni sustituir sensores, sino elegir mejor **cuándo conviene esperar** y **qué acción físicamente posible conviene priorizar** cuando hay varias opciones válidas o casi válidas. La misma capa de interlocks protege tanto al fixed como al dynamic.

## Fase 1 — El testbed con prioridades fijas, y el operario decidiendo el orden a ojo

El sistema físico solo puede funcionar si cada robot tiene un criterio para decidir qué hacer en el instante en que tiene más de una acción física posible a la vez — sin eso, no hay "modo manual" posible, los robots simplemente no sabrían a qué pieza ir. Por eso el testbed nació ya con un conjunto de reglas de prioridad fija (`fixed priorities`) en cada punto de conflicto. No son arbitrarias — cada una responde a una razón física concreta:

- **robot2** (clasificación en C2S2 / recogida de bantam / drenaje de IBS): prioridad `P1 > P2 > P3`. P1 (clasificar la pieza en C2S2) va primero porque ese sensor es el cuello de botella de todo el flujo aguas arriba — si C2S2 se queda ocupado, se atasca el conveyor2 entero y xarm1 no puede depositar nada nuevo. Liberar ese sensor pesa más que vaciar un buffer secundario (bantam) o un buffer de desbordamiento (IBS).
- **robot1** (retirar de C3 o C4 cuando ambos tienen pieza terminada a la vez): se elige la que lleva **más tiempo esperando** (comparando el timestamp de finalización de cada estación) — una regla de "primero en terminar, primero en servir" para evitar que una pieza se quede indefinidamente esperando mientras otras más recientes la adelantan.
- **xarm1** (retirar del láser terminado / alimentar C1S2 hacia el láser o conveyor2): prioridad `LASER > C1` — se retira primero el producto ya terminado antes de introducir trabajo nuevo, para no bloquear el puesto de láser con una pieza que ya no necesita procesado.

Sobre esa base de reglas fijas — que es lo que hacía que el sistema pudiera moverse en absoluto — era el operario quien decidía manualmente la secuencia de colores en la que se alimentaban las piezas al stack inicial (por ejemplo, `RBRBRB` para un lote de 3 azules y 3 rojas). Esa decisión se tomaba por intuición y experiencia acumulada, sin ningún modelo del comportamiento real de la célula — no había forma de saber si ese orden concreto era bueno o malo hasta después de correrlo. Era, por definición, subóptimo: las reglas de despacho ya eran físicamente razonadas, pero el orden de entrada no tenía ningún criterio objetivo detrás, solo la costumbre del operario.

## Fase 2 — Simulación + optimización del orden inicial

El siguiente paso fue construir una simulación de eventos discretos (SimPy) que replicara fielmente la célula física completa bajo esas mismas reglas de prioridad fija. Con esa simulación, se podía hacer fuerza bruta: probar todas las permutaciones posibles del orden de alimentación inicial y quedarse con la que minimizara el tiempo total de producción (makespan) bajo la política fija.

**Resultado real, documentado:** para un lote de 6 piezas (3 azules + 3 rojas), el orden sin optimizar (`RBRBRB`) daba `626.6s` simulados. El orden optimizado por fuerza bruta (`BRRRBB`) bajaba a `560.2s` simulados — **`66.4s` de ahorro, un 10.6%** — y se confirmó en hardware real: `552.962s`, con una fidelidad simulación-vs-realidad de apenas `-1.3%`.

Esto funcionaba bien — **para lotes pequeños**. El problema apareció al escalar: la simulación asume que cada acción dura exactamente lo que el modelo predice, pero la realidad física tiene variabilidad — un robot puede tardar unos segundos más o menos de lo previsto en un ciclo concreto. Para un lote pequeño ese desfase apenas importa. Pero en cuanto se acumulaba un desfase de unos pocos segundos en el momento equivocado, la secuencia física real dejaba de coincidir con la secuencia que la simulación había precalculado — y el sistema, al intentar seguir ciegamente esa secuencia ya desincronizada de la realidad, se rompía: esperaba una pieza que no estaba donde el mapa decía que debía estar.

## Fase 3 — El mapa de prioridades fijas con periodo de gracia

La solución no fue abandonar la guía precalculada, sino hacerla tolerante al desfase. Se introdujo un mecanismo de "mapa" (`classification_rules.py`, `MAP_GRACE_SEC`) que no sigue la secuencia de forma ciega: cuando el mapa anticipa que la siguiente acción "debería" ser otra distinta a la que la política reactiva haría por defecto, el robot **se detiene a propósito, pero solo un tiempo acotado** (el periodo de gracia) esperando a que la realidad alcance lo que el mapa predijo. Si la pieza esperada aparece dentro de ese margen, se sigue el mapa (`followed`). Si no aparece a tiempo, el sistema **no se bloquea** — cae de vuelta a la política reactiva fija y sigue produciendo con lo que hay disponible en ese instante (`timeout`, contabilizado pero no bloqueante).

Esto convirtió un sistema frágil (un desfase de segundos rompía la secuencia entera) en uno robusto: los pequeños desfases físicos ya no desincronizan permanentemente el mapa de la realidad, el sistema absorbe la variación y sigue produciendo. Esta es exactamente la distinción `matched` / `followed` / `timeout` que se audita en cada corrida de validación (`run_report.py`) — en las corridas reales documentadas, la inmensa mayoría de ciclos son `matched`, un puñado son `followed` (esperas de gracia de 5-10s que sí compensaron), y prácticamente ninguno cae en `timeout` real.

## Fase 4 — Un paso más allá: el mapa dinámico

Todo lo anterior optimizaba el **orden de entrada** bajo una política de despacho **fija** (`P1>P2>P3`, siempre igual). El siguiente salto fue preguntarse: ¿y si la política de despacho en sí misma pudiera ser mejor que fija, no solo el orden de piezas?

Se construyó un motor de búsqueda (`beam_search.py` + `dispatch_search2.py`) que, además de buscar el orden inicial, explora **decisiones alternativas de despacho** en los puntos de conflicto real — en particular, la opción de que robot2 **espere deliberadamente** (`WAIT`) a que bantam termine antes de clasificar la siguiente pieza de C2S2, en vez de clasificar siempre primero por regla fija. Esto replica, dentro del propio motor de búsqueda, el mismo tipo de decisión inteligente que el mapa de gracia ya hacía en producción real — pero ahora descubierta automáticamente por búsqueda, no codificada a mano.

**Resultados con números reales, no solo simulados:**

| Composición | Piezas | Ahorro simulado (dinámico vs. fixed optimizado) | Ahorro real en hardware |
|---|---:|---:|---:|
| 3B/3R/0G (`BRRBRB`) | 6 | +11.2% | **+12.0%** |
| 4B/5R/0G | 9 | +15.4% | **+16.1%** |
| 5B/4R/0G | 9 | +17.1% | **+16.9%** |
| 2B/2R/6G | 10 | +0.0% (caso de control) | **-0.7%** (ruido, no gana ni pierde) |
| 4B/4R/3G | 11 | +14.5% | **+14.9%** |
| 5B/5R/2G | 12 | +17.7% | **+18.3%** |
| 5B/5R/5G | 15 | +15.8% | **+16.0%** |
| 6B/6R/6G | 18 | +14.0% | **+14.3%** |

En las ocho corridas validadas físicamente, la fidelidad simulación-vs-realidad se mantuvo dentro de `±1-3%`. En los siete casos con congestión real, el ahorro medido en hardware siguió muy de cerca al ahorro simulado, con reducciones reales entre `12.0%` y `18.3%`. El caso de control (`2B/2R/6G`, con solo 2 piezas azules) confirma además que el mecanismo no inventa mejoras donde no las hay: cuando apenas circula tráfico por Bantam, no hay nada que el `WAIT` pueda optimizar, y tanto la simulación como la realidad coinciden en que el ahorro es esencialmente cero (`-0.7%` real, dentro del ruido normal del hardware).

**En el dataset actual (última actualización de tabla: 2026-07-15), el sistema cubre 87 composiciones distintas (de 6 a 18 piezas)**, generadas con la misma metodología: media de ahorro simulado `+9.96%`, mínimo `0.0%` (tres composiciones, todas con poco tráfico de azul), máximo `+19.2%`. 42 de esas 87 son búsquedas exhaustivas (cubren el 100% de las permutaciones posibles); el resto son muestreadas sobre espacios de hasta varios millones de permutaciones. Ver `docs/dynamic_maps_dataset.md` para la tabla completa.

## Por qué la comparación es justa

La comparación principal no es contra un orden manual débil, sino contra el **mejor orden inicial encontrado bajo la política fija**. Es decir: primero se le da a la política fija su mejor oportunidad, optimizando el stack inicial con la misma simulación. Solo después se compara contra el mapa dinámico. Por eso la mejora no significa "el sistema anterior era malo"; significa que una política fija razonable, incluso con el mejor orden de entrada encontrado, sigue perdiendo oportunidades cuando dos decisiones locales requieren criterios distintos en momentos distintos.

El ejemplo más claro es robot2: una regla fija como "liberar siempre C2S2 antes que descargar Bantam" es físicamente razonable la mayor parte del tiempo, porque evita bloquear conveyor2. Pero no siempre es óptima para el makespan global. En algunos estados conviene clasificar la pieza de C2S2; en otros conviene esperar unos segundos y descargar Bantam primero. Esa alternancia es precisamente lo que una prioridad global fija no puede representar y lo que el mapa dinámico sí captura.

## Alcance y límites actuales

Los resultados reales se apoyan en ocho composiciones validadas en hardware. El resto del dataset es simulado, aunque con un modelo que en esas ocho validaciones se mantuvo dentro de `±1-3%` frente al hardware. Además, no todas las 87 composiciones fueron buscadas exhaustivamente: 42 sí cubren el espacio completo, y el resto usan muestreo porque el número de permutaciones puede crecer hasta millones.

También hay una dependencia física importante: si cambia de forma significativa la posición de Bantam, las velocidades de los robots, las trayectorias o los tiempos de proceso, el dataset debe regenerarse o al menos recalibrarse. La ventaja es que ese coste está en la parte offline; el sistema real sigue ejecutando un mapa congelado y protegido, no una política aprendida en vivo.

## El hilo completo, de principio a fin

Poniendo las cuatro fases una detrás de otra sobre el mismo caso documentado de 6 piezas: orden manual sin optimizar (`626.6s`) → orden optimizado bajo política fija (`560.2s` sim / `552.962s` real, **-11.8%** sobre el punto de partida) → mapa dinámico (`497.3s` sim / `486.651s` real, **-22.3%** sobre el punto de partida original). Cada fase resolvió un problema real y medible de la anterior — el orden manual no tenía ningún criterio objetivo aunque los robots ya supieran actuar físicamente; la optimización por fuerza bruta no sobrevivía al desfase físico; el mapa de gracia lo hizo robusto pero seguía limitado a una política fija; el mapa dinámico encontró margen de mejora adicional que ninguna política fija, por bien elegida que estuviera, podía alcanzar por sí sola.

## Mensaje principal para una presentación

La tesis defendible es esta: **un sistema Plug-and-Plan no solo necesita optimizar el orden de entrada, necesita optimizar las decisiones de despacho que ocurren durante la corrida, pero sin perder seguridad física**. El mapa dinámico consigue ese equilibrio porque calcula offline una política específica para el lote actual, la ejecuta como mapa predefinido, y la protege en tiempo real con sensores, esperas acotadas y fallback reactivo.

En una presentación, la forma más clara de contarlo sería:

1. Primero, mostrar el layout físico y las rutas de rojo, azul y verde.
2. Segundo, explicar por qué las prioridades fijas eran necesarias y razonables.
3. Tercero, mostrar que optimizar solo el orden inicial ya ayuda, pero no resuelve los conflictos internos.
4. Cuarto, enseñar el salto conceptual: la misma situación local puede necesitar decisiones distintas según el futuro previsto de la corrida.
5. Quinto, cerrar con la evidencia: ocho corridas reales, 87 composiciones simuladas, ahorros reales de hasta `18.3%`, y un caso de control donde el método no fuerza una mejora inexistente.
