{
    'name': 'Shop Integration API',
    'version': '18.0.1.0.0',
    'category': 'Sales/API',
    'summary': 'REST API para integracion con e-commerce (Productos, Pedidos, Webhooks)',
    'author': 'Binaural',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'sale_stock', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/api_request_log_views.xml',
        'views/webhook_queue_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
