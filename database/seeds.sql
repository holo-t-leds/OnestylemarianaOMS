-- =========================================================================
-- SEEDS COMPLETOS — G.C.L. ONESTYLE MARIANA (OMS)
-- Base de Datos: onestyle_db (MySQL / MariaDB)
-- Convención de colores en static/img/: r = Rojo, n = Negro, ros = Rosado, b = Blanco
-- =========================================================================

-- 1. ROLES OFICIALES (RF-SEG-007, RF-SEG-012)
INSERT IGNORE INTO roles (id_rol, nombre_rol) VALUES
(1, 'Administradora'),
(2, 'Vendedora'),
(3, 'Clienta');

-- 2. USUARIOS INICIALES (Contraseñas con hash bcrypt de 'AdminOneStyle2026' y 'VentasOneStyle2026')
INSERT IGNORE INTO usuarios (id_usuario, fk_id_rol, nombre, apellido, email, contrasena, telefono, estado_usuario) VALUES
(1, 1, 'Mariana', 'OneStyle', 'admin@onestylemariana.co', '$2b$12$KIXQ1V2W3X4Y5Z6A7B8C9O0P1Q2R3S4T5U6V7W8X9Y0Z1A2B3C4D5', '3001112233', TRUE),
(2, 2, 'Valeria', 'Asesora', 'vendedora@onestylemariana.co', '$2b$12$KIXQ1V2W3X4Y5Z6A7B8C9O0P1Q2R3S4T5U6V7W8X9Y0Z1A2B3C4D5', '3004445566', TRUE),
(3, 3, 'Camila', 'Restrepo', 'clienta@onestylemariana.co', '$2b$12$KIXQ1V2W3X4Y5Z6A7B8C9O0P1Q2R3S4T5U6V7W8X9Y0Z1A2B3C4D5', '3109876543', TRUE);

-- 3. CATEGORÍAS MAESTRAS DEL CATÁLOGO (RF-CAT-008 a RF-CAT-011)
INSERT IGNORE INTO categorias (id_categoria, nombre_categoria, descripcion_categoria, estado) VALUES
(1, 'Corsets', 'Corsets arquitectónicos y lencería de autor', TRUE),
(2, 'Blusas', 'Blusas y crop tops americanos de confección importada', TRUE),
(3, 'Bodies', 'Bodies y enterizos nocturnos en malla y encaje francés', TRUE),
(4, 'Pantalones', 'Pantalones en cuerina y denim wide leg exclusivo', TRUE),
(5, 'Vestidos', 'Vestidos americanos importados de temporada', TRUE),
(6, 'Conjuntos', 'Conjuntos de sastrería y chalecos de edición limitada', TRUE);

-- 4. ATRIBUTOS MAESTROS: TALLAS Y COLORES (RF-CAT-013 a RF-CAT-016)
INSERT IGNORE INTO tallas (id_talla, nombre_talla, estado) VALUES
(1, 'XS', TRUE),
(2, 'S', TRUE),
(3, 'M', TRUE),
(4, 'L', TRUE),
(5, 'XL', TRUE);

-- Convención: 1=Negro (n), 2=Marfil, 3=Canela (c), 4=Rojo (r), 5=Azul, 6=Blanco (b), 7=Rosado (ros)
INSERT IGNORE INTO colores (id_color, nombre_color, codigo_hex, estado) VALUES
(1, 'Negro', '#17140F', TRUE),
(2, 'Marfil', '#EFE7D5', TRUE),
(3, 'Canela', '#8B5A34', TRUE),
(4, 'Rojo', '#A31F2D', TRUE),
(5, 'Azul', '#4E6484', TRUE),
(6, 'Blanco', '#F8F6F0', TRUE),
(7, 'Rosado', '#E8A5B8', TRUE);

-- 5. PRODUCTOS MAESTROS DEL CATÁLOGO CON IMÁGENES REALES (RF-CAT-001 a RF-CAT-004)
INSERT IGNORE INTO producto (id_producto, fk_id_categoria, nombre_producto, descripcion_producto, precio_detallista, url_imagen_principal, estado_visibilidad) VALUES
(1,  1, 'Corset Encaje Marfil', 'Encaje francés, varillaje arquitectónico', 120000.00, 'img/corset34-47.jpg', TRUE),
(2,  1, 'Corset Canela de Lujo', 'Detalles de encaje premium importado', 145000.00, 'img/corset-canela.jpg', TRUE),
(3,  3, 'Body Americano Nocturno', 'Manga larga y silueta minimalista (bodysamericanosB-N-ROS-C)', 128000.00, 'img/body-nocturno.jpg', TRUE),
(4,  1, 'Corset Encaje Noir', 'Diseño floral contrastante en encaje negro', 160000.00, 'img/corset-noir.jpg', TRUE),
(5,  2, 'Top Escote Profundo', 'Silueta fluida, cuello halter importado', 135000.00, 'img/top-escote.jpg', TRUE),
(6,  4, 'Pantalón Cuerina & Denim', 'Detalle frontal ajustable de tiro alto', 120000.00, 'img/pantaloncuerina.jpg', TRUE),
(7,  2, 'Top Esencial Carmesí', 'Ajuste perfecto, manga corta', 115000.00, 'img/top-carmesi.jpg', TRUE),
(8,  1, 'Corset Lencería Blanc', 'Botones frontales decorativos en blanco puro', 180000.00, 'img/corset-blanc.jpg', TRUE),
(9,  4, 'Jeans Wide Leg Premium', 'Denim importado, corte relajado', 165000.00, 'img/jeans-wide.jpg', TRUE),
(10, 5, 'Vestido Americano Importado', 'Colección americana en Blanco (B), Negro (N) y Rojo (R)', 210000.00, 'img/vestidoamericanoB.jpg', TRUE),
(11, 2, 'Crop Top Americano', 'Diseño versátil importado en Blanco (croptopB) y Negro (croptopN)', 118000.00, 'img/croptopB.jpg', TRUE),
(12, 2, 'Blusa Americana Importada', 'Tejido suave en Rosado (ROS), Blanco (B) y Negro (N)', 132000.00, 'img/blusaamericana.jpg', TRUE),
(13, 3, 'Enterizo Nocturno Manga Larga', 'Silueta esculpida de manga larga en Negro Obsidiana (N)', 195000.00, 'img/ENTERIZONEGROMANGALARGA.jpg', TRUE),
(14, 6, 'Conjunto Sastre Supreme', 'Dos piezas estructuradas y chaleco sastre (Negro, Blanco, Canela)', 225000.00, 'img/conjuntosupreme.jpg', TRUE);

-- 6. VARIANTES DE PRODUCTO CON SKU ÚNICO POR COLOR (RF-CAT-005 / RN-CAT-005)
INSERT IGNORE INTO producto_atributo (id_variante, fk_id_producto, fk_id_talla, fk_id_color, codigo_sku, precio_variante, estado) VALUES
(1,  1,  1, 2, 'OSM-COR-MAR-XS',    120000.00, TRUE),
(2,  1,  2, 6, 'OSM-COR-MAR-B-S',   120000.00, TRUE),
(3,  1,  2, 1, 'OSM-COR-MAR-N-S',   120000.00, TRUE),
(4,  2,  2, 3, 'OSM-COR-CAN-S',     145000.00, TRUE),
(5,  2,  2, 1, 'OSM-COR-CAN-N-S',   145000.00, TRUE),
(6,  3,  2, 1, 'OSM-BOD-NOC-N-S',   128000.00, TRUE),
(7,  3,  2, 6, 'OSM-BOD-NOC-B-S',   128000.00, TRUE),
(8,  3,  2, 7, 'OSM-BOD-NOC-ROS-S', 128000.00, TRUE),
(9,  4,  2, 1, 'OSM-COR-NOI-N-S',   160000.00, TRUE),
(10, 4,  2, 6, 'OSM-COR-NOI-B-S',   160000.00, TRUE),
(11, 5,  2, 1, 'OSM-TOP-ESC-N-S',   135000.00, TRUE),
(12, 5,  2, 4, 'OSM-TOP-ESC-R-S',   135000.00, TRUE),
(13, 6,  2, 1, 'OSM-PAN-CUE-N-S',   120000.00, TRUE),
(14, 7,  2, 4, 'OSM-TOP-CAR-R-S',   115000.00, TRUE),
(15, 8,  2, 6, 'OSM-COR-BLA-B-S',   180000.00, TRUE),
(16, 9,  3, 5, 'OSM-JEA-WID-M',     165000.00, TRUE),
(17, 10, 2, 6, 'OSM-VES-AME-B-S',   210000.00, TRUE),
(18, 10, 2, 1, 'OSM-VES-AME-N-S',   210000.00, TRUE),
(19, 10, 2, 4, 'OSM-VES-AME-R-S',   210000.00, TRUE),
(20, 11, 2, 6, 'OSM-CRP-AME-B-S',   118000.00, TRUE),
(21, 11, 2, 1, 'OSM-CRP-AME-N-S',   118000.00, TRUE),
(22, 12, 2, 6, 'OSM-BLU-AME-B-S',   132000.00, TRUE),
(23, 12, 2, 7, 'OSM-BLU-AME-ROS-S', 132000.00, TRUE),
(24, 12, 2, 1, 'OSM-BLU-AME-N-S',   132000.00, TRUE),
(25, 13, 2, 1, 'OSM-ENT-NOC-N-S',   195000.00, TRUE),
(26, 14, 2, 3, 'OSM-CON-SUP-C-S',   225000.00, TRUE),
(27, 14, 2, 1, 'OSM-CON-SUP-N-S',   225000.00, TRUE),
(28, 14, 2, 6, 'OSM-CON-SUP-B-S',   225000.00, TRUE);

-- 7. INVENTARIO INICIAL POR VARIANTE (RF-CAT-006 y RF-CAT-007)
INSERT IGNORE INTO inventario (id_inventario, fk_id_variante, stock_real, stock_reservado, punto_reposicion) VALUES
(1,  1,  8, 0, 3),
(2,  2,  6, 0, 3),
(3,  3,  5, 0, 3),
(4,  4,  7, 0, 3),
(5,  5,  9, 0, 3),
(6,  6,  6, 0, 3),
(7,  7,  5, 0, 3),
(8,  8,  7, 0, 3),
(9,  9, 10, 0, 3),
(10, 10, 8, 0, 3),
(11, 11, 6, 0, 3),
(12, 12, 5, 0, 3),
(13, 13, 4, 0, 3),
(14, 14, 7, 0, 3),
(15, 15, 5, 0, 3),
(16, 16, 8, 0, 3),
(17, 17, 6, 0, 3),
(18, 18, 6, 0, 3),
(19, 19, 6, 0, 3),
(20, 20, 7, 0, 3),
(21, 21, 7, 0, 3),
(22, 22, 6, 0, 3),
(23, 23, 6, 0, 3),
(24, 24, 6, 0, 3),
(25, 25, 5, 0, 3),
(26, 26, 6, 0, 3),
(27, 27, 6, 0, 3),
(28, 28, 6, 0, 3);

-- 8. CENTRO DE AYUDA, CATEGORÍAS FAQ Y SOPORTE (RF-FAQ-001 a RF-FAQ-011)
INSERT IGNORE INTO categorias_faq (id_categoria, nombre_categoria, slug, icono, order_index, estado) VALUES
(1, 'Envíos y Entregas', 'envios-y-entregas', 'bi-truck', 1, TRUE),
(2, 'Medios de Pago', 'medios-de-pago', 'bi-credit-card', 2, TRUE),
(3, 'Cambios y Devoluciones', 'cambios-y-devoluciones', 'bi-arrow-repeat', 3, TRUE),
(4, 'Cuidado de Prendas y Tallas', 'cuidado-y-tallas', 'bi-rulers', 4, TRUE);

INSERT IGNORE INTO faq (id_faq, id_categoria, pregunta, respuesta, estado, orden, helpful_count, not_helpful_count) VALUES
(1, 1, '¿Cuáles son los tiempos y costos de envío en Colombia?', 'Realizamos despachos Express asegurados a toda Colombia. En Bogotá la entrega toma de 1 a 2 días hábiles y en el resto del país de 2 a 4 días hábiles.', TRUE, 1, 5, 0),
(2, 1, '¿Cómo puedo rastrear el estado de mi pedido?', 'Con tu código único de orden (ej. ORD-00001) puedes consultar en tiempo real la etapa de preparación y despacho desde la sección Seguimiento.', TRUE, 2, 3, 0),
(3, 2, '¿Qué medios de pago aceptan a través del Concierge?', 'Aceptamos transferencia inmediata por PSE, Nequi, Bancolombia y tarjetas débito/crédito mediante enlace seguro verificado por nuestra asesora en WhatsApp.', TRUE, 1, 4, 0),
(4, 3, '¿Cuál es la política de cambios por talla o referencia?', 'Puedes solicitar cambio de talla dentro de los primeros 15 días calendario posteriores a la entrega, siempre que la prenda conserve sus etiquetas originales.', TRUE, 1, 2, 0),
(5, 4, '¿Cómo elegir mi talla ideal en corsets y blusas estructuradas?', 'En cada ficha de producto encontrarás la guía de medidas exactas de busto y cintura. Si estás entre dos tallas, en corsets con varillaje recomendamos elegir la talla superior.', TRUE, 1, 6, 0);

INSERT IGNORE INTO configuracion_soporte (id_contacto, tipo_contacto, destino, horario_atencion, mensaje_predeterminado, estado) VALUES
(1, 'WhatsApp', '573001234567', 'Lunes a Sábado de 9:00 a.m. a 7:00 p.m.', 'Hola, tengo una consulta sobre OneStyle Mariana que no encontré en las preguntas frecuentes.', TRUE);
