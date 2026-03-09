# Contexto

Trabajo en un firma legal especializada en visas humanitarias para estados unidos, visas como vawa, visa t, y visa u, la gran mayoría de la comunicación se realiza mediante llamadas telefónicas en donde los clientes cuentan su historia, se les pide su testimonio, se les notifica de los avances o de las dificultades de su caso, se le llama para hacer seguimiento de su caso como de los documentos que les hace falta, entre otras cosas, cada área de la firma legal realiza llamadas según su conveniencia o su necesidad. Por otro lado los archivos y documentos que sirven para formar el caso se suben a dropbox en donde además se suben los audios, actualmente hay más de 50 TB almacenados pero la información no tiene una estructura clara, la forma de tener cada caso individual es generando una carpeta de cliente, esta carpeta se genera con una ley no escrita, la cual tiene cierta estructura de carpetas dentro de la carpeta de cliente, aunque analizando los datos he visto que no se cumple un patrón de ley ya que hay muchas faltas de ortografía, símbolos adicionales y errores fatales al generar estas carpetas, afortunadamente he generado un algoritmo que permite la recolección de las carpetas de clientes o al menos de la mayoría de ellos, encontrado más de 30 mil carpetas de clientes, este proceso se realiza con ayuda de un script que tiene todo esto mapeado, sin embargo, es importante señalar que este script se ayuda de una base de datos la cual tiene mapeado el árbol de archivos de dropbox, esta base de datos se creo a partir de otro proyecto que tenia esta tarea de indexar el árbol de los 50 TB, esta base de datos se encuentra en un archivo .sql ya que se descargo así de la nube con el fin de hacer pruebas en local, llamaremos a esta base como backup_dropbox.sql, por otro lado, las llamadas de los clientes se transcriben pero dado a que no existe la infraestructura operacional, es decir, no hay procedimientos mapeados y establecidos, se han detectado al rededor de 60 mil audios que no se han transcrito de sólo una área, el área de Psychology, es necesario, subir estos audios a la carpeta de cliente en cierta ruta dentro de la carpeta del cliente. Cabe mencionar que estos 60 mil audios están almacenados en el servidor de la cede en la que trabajo, por lo que, el equipo de IT me proporciono datos de dicha base de datos, la cual por cada registro tiene sólo contiene la ruta de la carpeta en donde se encuentra dicho audio con el nombre del archivo, además de otros campos que me son de utilidad como el id del colaborador de la firma que realizo la llamada, lo cual nos lleva a otra tabla la cual contiene el área de dicho colaborador, por lo que IT me proporciono 3 .sql para realizar pruebas y subir a un contenedor docker mi proyecto que subirá los audios a la carpeta correspondiente del cliente, dichos .sql tiene pocos registros ya que son de prueba pero datos reales, los .sql son los siguientes: “audios.sql” el cual tiene la ruta de los audios, el id del colaborador y el nombre del cliente, “CREACION DE TABLAS.sql” el cual contiene la definición de las tablas SQL que voy a ocupar y “user_sql.sql” el cual tiene el ID de los colaboradores en donde se encuentra su área.


Mi propuesta actual es realizar pruebas en local con docker-compose para cuando les de el proyecto sólo tenga que cambiar la topología, no el código, para que lo ejecuten en el servidor que sólo sea una cuestión de cambiar sólo las variables de entorno y el docker-compose.yaml. Mi idea es usar una arquitectura similar a la siguiente:

updaudios/
├── docker-compose.yaml
├── .env.local                   # Variables de entorno
├── app/
│   ├── pipeline/
│   │   ├── step0_audios.py
│   │   ├── step1_dropbox.py
│   │   ├── step2_cruce.py
│   │   ├── step3_paths.py
│   │   ├── step4_upload.py
│   │   ├── step5_audit.py
│   ├── services/
│   │   ├── auth_service.py
│   ├── Dockerfile               # Instrucciones para construir el script
│   ├── requirements.txt         # Dependencias
│   ├── database.py
│   ├── config.py
│   └── main.py                  # Código principal
├── audios_de_prueba/            # Audios falsos de prueba
├── db_dropbox_init/
│   └── backup_dropbox.sql       # base de datos
└── db_it_init/
    ├── 01_CREACION_DE_TABLAS.sql
    ├── 02_user_sql.sql
    └── 03_audios.sql


Aunque estoy dispuesto a considerar cambios.


Actualmente mi proyecto funciona con las siguientes características y limitaciones:

1.- El consumo de los datos proviene de:
a. Una base de datos que esta corriendo en un contenedor docker el cual recientemente fue eliminado, base de datos que es la misma que el archivo backup_dropbox.sql.
b. GCS, en donde se encuentran más de 8 mil audios, audios que pertenecen a los 60 mil audios.

2.- El pipeline esta basado en los scripts que están en la carpeta raíz del proyecto, es decir: “audios_nombres.py”, “audios_path_dropbox.py”, “auditoria_fase_n.py”, “cruce.py”, “dropbox_clean_analysis.py” y “migrar_audios_dropbox.py”

3.- El pipeline esta desarrollado bajo la conexión de cvs, es decir, la salida de un script de pipeline usualmente usa un csv y genera un csv que será la entrada a otro script.

4.- El pipeline aún no sea probado (La carpeta /home/ortega/updaudios/pipeline y el /home/ortega/updaudios/main.py).

5.- Actualmente la carpeta /home/ortega/updaudios/app es una semi copia (no se copiaron todos los archivos que contiene dicha carpeta) del proyecto que genero la base de datos de dropbox, base que ahora consumiremos para el proceso.

6.- IT me proporciono el script SQL que ejecutan para obtener los audios que necesito:

SELECT ruta_llamada AS path, nombre_archivo AS file_name, nombre_cliente AS name
FROM mendoza_box.audios_descargados AS audios, RH.usuarios AS filtro 
WHERE audios.id_user = filtro.id_user 
AND filtro.area= 'PSYCHOLOGY' 
AND (audios.nombre_cliente != '' OR audios.nombre_cliente IS NOT NULL) 
AND audios.duracion >= '00:00:50'
LIMIT 10;
