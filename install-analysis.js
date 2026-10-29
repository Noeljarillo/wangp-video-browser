module.exports = {
  run: [
    // Optional analysis add-on: its own venv in app/analysis/env, separate from
    // the dependency-free browser in app/env. Removing it (Reset) leaves the
    // browser fully working.
    {
      method: "shell.run",
      params: {
        venv: "env",
        path: "app/analysis",
        message: [
          "uv pip install -r requirements.txt"
        ]
      }
    },
    {
      method: "script.start",
      params: {
        uri: "torch.js",
        params: {
          venv: "env",
          path: "app/analysis"
        }
      }
    },
    {
      method: "notify",
      params: {
        html: "Analysis add-on installed - restart the browser to start analysing your library"
      }
    }
  ]
}
