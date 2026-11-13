# Referencias · HTCC AMG8833

Documentación externa que se usó para entender el hardware, los protocolos y las
libertades del proyecto. No es una bibliografía decorativa: cada enlace apunta a
la fuente que explica una decisión concreta.

## Fuentes técnicas

| Fuente | Para qué se consultó |
|---|---|
| [Heltec CubeCell](https://docs.heltec.org/en/node/cubecell/index.html) | Documentación de la serie HTCC. |
| [LoRaWAN 1.0.4](https://lora-alliance.org/resource_hub/lorawan-specification-v1-0-4/) | Especificación del protocolo LoRaWAN. |
| [AMG8833](https://learn.adafruit.com/adafruit-amg8833-8x8-thermal-camera-sensor) | Sensor térmico 8x8 y su I2C. |
| [Arduino Documentation](https://docs.arduino.cc/) | Referencia de placas, IDE y API. |

## Versiones de este repositorio

`HTCC_AB01_AMG8833_Thermal_v1`, `HTCC_AB02A_AMG8833_Thermal`, `HTCC_AB02A_AMG8833_Thermal_Acelerometro`, `HTCC_AB02A_AMG8833_Thermal_v2`

Cada carpeta puede tener dependencias y versiones distintas. Cuando el código
depende de una versión específica, esa versión está declarada en el README o en
el archivo de configuración de la carpeta, no en este documento.

## Criterio de preservación

- El código y los documentos se copiaron desde la carpeta original de trabajo.
- Se excluyeron `.git`, dependencias instaladas, compilados, registros y bases
  de datos locales.
- Se redactaron tokens, claves privadas y contraseñas detectadas en texto.
- Las plantillas `.example`, `.sample` y los valores de demostración se
  conservan porque documentan la configuración esperada.

## Limitaciones conocidas

Un nodo térmico remoto no se puede reconfigurar sin ir a buscarlo, y cada join consume batería y tiempo de aire.

La documentación de cada versión describe el alcance real. Si una función no
está implementada, se dice; si un hardware no fue probado, también.
