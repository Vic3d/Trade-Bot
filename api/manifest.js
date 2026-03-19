module.exports = function handler(req, res) {
  res.setHeader('Content-Type', 'application/manifest+json');
  res.setHeader('Cache-Control', 'public, max-age=3600');
  res.json({
    name: 'TradeMind',
    short_name: 'TradeMind',
    description: 'Professional Trading Dashboard',
    start_url: '/',
    display: 'standalone',
    background_color: '#0d1117',
    theme_color: '#7c3aed',
    icons: [
      { src: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🎩</text></svg>', sizes: '192x192', type: 'image/svg+xml' },
      { src: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🎩</text></svg>', sizes: '512x512', type: 'image/svg+xml' }
    ]
  });
};
