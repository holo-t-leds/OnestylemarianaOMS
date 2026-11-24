-- MySQL/MariaDB DDL Schema
-- Based on the requirements and ent.puml

CREATE TABLE IF NOT EXISTS roles (
    id_rol INT AUTO_INCREMENT PRIMARY KEY,
    nombre_rol VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_rol INT NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    contrasena VARCHAR(255) NULL,
    google_id VARCHAR(255) NULL UNIQUE,
    reset_token_hash VARCHAR(255) NULL,
    reset_token_expira DATETIME NULL,
    telefono VARCHAR(20),
    tipo_documento VARCHAR(20) NULL,
    documento VARCHAR(30) NULL,
    direccion VARCHAR(255) NULL,
    estado_usuario BOOLEAN DEFAULT TRUE,
    fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_rol) REFERENCES roles(id_rol)
);

CREATE TABLE IF NOT EXISTS auditoria (
    id_log INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_usuario_accion INT NOT NULL,
    tipo_accion VARCHAR(100) NOT NULL,
    tabla_afectada VARCHAR(100) NOT NULL,
    id_registro_afectado INT,
    valor_anterior TEXT,
    valor_nuevo TEXT,
    ip_address VARCHAR(45) NULL,
    user_agent VARCHAR(255) NULL,
    fecha_accion DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_usuario_accion) REFERENCES usuarios(id_usuario)
);

CREATE TABLE IF NOT EXISTS categorias (
    id_categoria INT AUTO_INCREMENT PRIMARY KEY,
    nombre_categoria VARCHAR(100) NOT NULL UNIQUE,
    descripcion_categoria TEXT,
    estado BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS tallas (
    id_talla INT AUTO_INCREMENT PRIMARY KEY,
    nombre_talla VARCHAR(10) NOT NULL UNIQUE,
    estado BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS colores (
    id_color INT AUTO_INCREMENT PRIMARY KEY,
    nombre_color VARCHAR(50) NOT NULL UNIQUE,
    codigo_hex VARCHAR(10),
    estado BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS producto (
    id_producto INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_categoria INT NOT NULL,
    nombre_producto VARCHAR(150) NOT NULL,
    descripcion_producto TEXT,
    precio_detallista DECIMAL(12,2) NOT NULL CHECK (precio_detallista > 0),
    url_imagen_principal VARCHAR(255),
    estado_visibilidad BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (fk_id_categoria) REFERENCES categorias(id_categoria) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS producto_imagen (
    id_imagen INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_producto INT NOT NULL,
    url_imagen VARCHAR(500) NOT NULL,
    formato VARCHAR(10),
    es_principal BOOLEAN DEFAULT FALSE,
    fecha_carga DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_producto) REFERENCES producto(id_producto) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS producto_atributo (
    id_variante INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_producto INT NOT NULL,
    fk_id_talla INT NOT NULL,
    fk_id_color INT NOT NULL,
    codigo_sku VARCHAR(60) UNIQUE,
    precio_variante DECIMAL(12,2) NULL CHECK (precio_variante IS NULL OR precio_variante > 0),
    estado BOOLEAN DEFAULT TRUE,
    UNIQUE KEY uk_producto_talla_color (fk_id_producto, fk_id_talla, fk_id_color),
    FOREIGN KEY (fk_id_producto) REFERENCES producto(id_producto) ON DELETE RESTRICT,
    FOREIGN KEY (fk_id_talla) REFERENCES tallas(id_talla) ON DELETE RESTRICT,
    FOREIGN KEY (fk_id_color) REFERENCES colores(id_color) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS inventario (
    id_inventario INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_variante INT NOT NULL UNIQUE,
    stock_real INT NOT NULL CHECK (stock_real >= 0),
    stock_reservado INT NOT NULL DEFAULT 0 CHECK (stock_reservado >= 0),
    punto_reposicion INT NOT NULL DEFAULT 5 CHECK (punto_reposicion >= 0),
    FOREIGN KEY (fk_id_variante) REFERENCES producto_atributo(id_variante) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS carrito (
    id_carrito INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_usuario INT NULL,
    session_id VARCHAR(100) NULL,
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_usuario) REFERENCES usuarios(id_usuario)
);

CREATE TABLE IF NOT EXISTS detalle_carrito (
    id_detalle_carrito INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_carrito INT NOT NULL,
    fk_id_variante INT NOT NULL,
    cantidad INT NOT NULL CHECK (cantidad > 0),
    precio DECIMAL(12,2) NOT NULL,
    subtotal DECIMAL(12,2) NOT NULL,
    cantidad_reservada INT NOT NULL DEFAULT 0 CHECK (cantidad_reservada >= 0),
    fecha_expiracion DATETIME,
    FOREIGN KEY (fk_id_carrito) REFERENCES carrito(id_carrito) ON DELETE CASCADE,
    FOREIGN KEY (fk_id_variante) REFERENCES producto_atributo(id_variante) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS inventario_reserva (
    id_reserva INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_variante INT NOT NULL,
    fk_id_carrito INT NULL,
    fk_id_usuario INT NULL,
    session_id VARCHAR(100) NULL,
    cantidad_reservada INT NOT NULL CHECK (cantidad_reservada > 0),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    estado ENUM('activa', 'expirada', 'liberada', 'confirmada') NOT NULL DEFAULT 'activa',
    FOREIGN KEY (fk_id_variante) REFERENCES producto_atributo(id_variante) ON DELETE RESTRICT,
    FOREIGN KEY (fk_id_carrito) REFERENCES carrito(id_carrito) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS pedido (
    id_pedido INT AUTO_INCREMENT PRIMARY KEY,
    codigo_orden VARCHAR(30) UNIQUE NOT NULL,
    fk_id_usuario INT NULL,
    fk_id_vendedora_asig INT NULL,
    metodo_entrega VARCHAR(80) NOT NULL DEFAULT 'Domicilio Express',
    estado_pedido ENUM(
        'Registrado', 'Confirmado', 'En Empaque', 'Despachado', 'Entregado', 'Cancelado',
        'PENDIENTE_PAGO', 'CONFIRMADO', 'EN_PREPARACION', 'DESPACHADO', 'ENTREGADO', 'CANCELADO'
    ) NOT NULL DEFAULT 'Registrado',
    fecha_pedido DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega DATETIME NULL,
    subtotal DECIMAL(12,2) NOT NULL DEFAULT 0.00 CHECK (subtotal >= 0),
    costo_envio DECIMAL(12,2) NOT NULL DEFAULT 0.00 CHECK (costo_envio >= 0),
    impuestos DECIMAL(12,2) NOT NULL DEFAULT 0.00 CHECK (impuestos >= 0),
    total_pedido DECIMAL(12,2) NOT NULL CHECK (total_pedido >= 0),
    url_comprobante_whatsapp TEXT,
    FOREIGN KEY (fk_id_usuario) REFERENCES usuarios(id_usuario) ON DELETE SET NULL,
    FOREIGN KEY (fk_id_vendedora_asig) REFERENCES usuarios(id_usuario) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS detalle_pedido (
    id_detalle_pedido INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_pedido INT NOT NULL,
    fk_id_variante INT NOT NULL,
    cantidad INT NOT NULL CHECK (cantidad > 0),
    precio DECIMAL(12,2) NOT NULL CHECK (precio >= 0),
    subtotal DECIMAL(12,2) NOT NULL CHECK (subtotal >= 0),
    FOREIGN KEY (fk_id_pedido) REFERENCES pedido(id_pedido) ON DELETE CASCADE,
    FOREIGN KEY (fk_id_variante) REFERENCES producto_atributo(id_variante) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS historial_pedido (
    id_historial INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_pedido INT NOT NULL,
    estado_anterior VARCHAR(50),
    estado VARCHAR(50) NOT NULL,
    fk_id_usuario_responsable INT NULL,
    motivo_cambio VARCHAR(255),
    fecha_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_pedido) REFERENCES pedido(id_pedido) ON DELETE CASCADE,
    FOREIGN KEY (fk_id_usuario_responsable) REFERENCES usuarios(id_usuario) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS domicilio (
    id_domicilio INT AUTO_INCREMENT PRIMARY KEY,
    fk_id_pedido INT NOT NULL,
    direccion_envio TEXT NOT NULL,
    barrio VARCHAR(100),
    ciudad VARCHAR(100) NOT NULL,
    telefono VARCHAR(20),
    observaciones TEXT,
    FOREIGN KEY (fk_id_pedido) REFERENCES pedido(id_pedido)
);

CREATE TABLE IF NOT EXISTS categorias_faq (
    id_categoria INT AUTO_INCREMENT PRIMARY KEY,
    nombre_categoria VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(80) UNIQUE NOT NULL,
    icono VARCHAR(50) DEFAULT 'bi-question-circle',
    order_index INT NOT NULL DEFAULT 1,
    estado BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS faq (
    id_faq INT AUTO_INCREMENT PRIMARY KEY,
    id_categoria INT NOT NULL,
    pregunta VARCHAR(255) NOT NULL,
    respuesta TEXT NOT NULL,
    estado BOOLEAN DEFAULT TRUE,
    orden INT NOT NULL CHECK (orden > 0),
    helpful_count INT NOT NULL DEFAULT 0 CHECK (helpful_count >= 0),
    not_helpful_count INT NOT NULL DEFAULT 0 CHECK (not_helpful_count >= 0),
    fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    usuario_actualizacion INT NULL,
    UNIQUE KEY uk_categoria_orden (id_categoria, orden),
    INDEX idx_faq_pregunta (pregunta),
    FULLTEXT INDEX idx_faq_busqueda (pregunta, respuesta),
    FOREIGN KEY (id_categoria) REFERENCES categorias_faq(id_categoria) ON DELETE RESTRICT,
    FOREIGN KEY (usuario_actualizacion) REFERENCES usuarios(id_usuario) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS configuracion_soporte (
    id_contacto INT AUTO_INCREMENT PRIMARY KEY,
    tipo_contacto VARCHAR(50) NOT NULL,
    destino VARCHAR(255) NOT NULL,
    horario_atencion VARCHAR(255),
    mensaje_predeterminado TEXT,
    estado BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ticket_soporte (
    id_ticket INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    contacto VARCHAR(150) NOT NULL,
    asunto VARCHAR(180) NOT NULL,
    mensaje TEXT NOT NULL,
    fk_id_pedido INT NULL,
    codigo_orden VARCHAR(30) NULL,
    estado ENUM('ABIERTO', 'EN_PROCESO', 'RESUELTO') NOT NULL DEFAULT 'ABIERTO',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (fk_id_pedido) REFERENCES pedido(id_pedido) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS reporte (
    id_reporte INT AUTO_INCREMENT PRIMARY KEY,
    id_usuario INT NOT NULL,
    tipo_reporte VARCHAR(150) NOT NULL,
    fecha_generacion DATETIME DEFAULT CURRENT_TIMESTAMP,
    periodo_inicio DATETIME,
    periodo_fin DATETIME,
    descripcion TEXT,
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);
