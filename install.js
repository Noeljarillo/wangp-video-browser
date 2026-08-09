module.exports = {
  run: [
    // The browser itself is standard-library only, but a venv keeps the launcher
    // on the conventional install/start/reset lifecycle and isolates future deps.
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app",
        message: [
          "uv pip install -r requirements.txt"
        ]
      }
    },
    {
      method: "notify",
      params: {
        html: "Installation completed - click Start to browse your WanGP outputs"
      }
    }
  ]
}
