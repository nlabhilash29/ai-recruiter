class WebGLRenderer {
  constructor() {
    this.domElement = document.createElement('canvas');
  }
  setSize() {}
  setPixelRatio() {}
  render() {}
  dispose() {}
}

class BufferGeometry {
  setAttribute() {}
}

module.exports = {
  Scene: class { add() {} },
  PerspectiveCamera: class {},
  WebGLRenderer,
  AmbientLight: class {},
  BufferGeometry,
  BufferAttribute: class {},
  PointsMaterial: class {},
  Points: class {},
  MeshStandardMaterial: class {},
  Mesh: class {},
};
