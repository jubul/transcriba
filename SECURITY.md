# Política de seguridad

## Versiones con soporte

| Versión | Soporte |
|---|---|
| 0.x (rama principal) | Sí |

## Reportar una vulnerabilidad

No abras un issue público. Usá el reporte privado de GitHub: pestaña **Security → Report a vulnerability** en https://github.com/jubul/transcriba/security. Respondemos en un plazo de 7 días y coordinamos la publicación del arreglo con quien reporta.

Interesa especialmente todo lo que afecte a una conferencia en vivo: acceso al panel o a la ingesta sin token, inyección de audio o de subtítulos en una sala ajena, fuga de la API key o de las transcripciones, y cualquier forma de dejar caer las salas de un evento.

## Recomendaciones para operar

- Configurar siempre `server.admin_token` antes de exponer el servidor a una red.
- Servir por HTTPS con un reverse proxy; nunca exponer el puerto directo a Internet.
- La API key de Gemini va en `.env` (ignorado por git), no en el YAML ni en capturas de pantalla.
- `data/` contiene las transcripciones: respaldarlo y tratarlo como contenido del evento.
