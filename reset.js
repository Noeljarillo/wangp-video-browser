module.exports = {
  run: [
    // Only generated state is removed - `app` holds this launcher's own source.
    {
      method: "fs.rm",
      params: {
        path: "app/env"
      }
    },
    {
      method: "fs.rm",
      params: {
        path: "app/analysis/env"
      }
    },
    {
      method: "fs.rm",
      params: {
        path: "app/.cache"
      }
    }
  ]
}
