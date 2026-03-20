module.exports = {
  apps: [
    {
      name: 'rbis-backend',
      script: 'uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8000 --log-level info',
      cwd: '/home/user/webapp/backend',
      interpreter: 'none',
      env: { PYTHONPATH: '/home/user/webapp/backend' },
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      max_restarts: 5,
    },
    {
      name: 'rbis-frontend',
      script: 'npx',
      args: 'vite preview --host 0.0.0.0 --port 5173 --outDir dist',
      cwd: '/home/user/webapp/frontend',
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
    },
  ],
}
