import { useEffect, useRef } from "react";
import * as THREE from "three";
import { FontLoader } from "three/examples/jsm/loaders/FontLoader";
import { TextGeometry } from "three/examples/jsm/geometries/TextGeometry";

export default function IntroAnimation({ onComplete }) {
  const mountRef = useRef(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    const mount = mountRef.current;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      onCompleteRef.current();
    };
    const giveUp = window.setTimeout(finish, 2800);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const particlesGeometry = new THREE.BufferGeometry();
    const particlesCount = 900;
    const particlesPositions = new Float32Array(particlesCount * 3);
    for (let i = 0; i < particlesCount * 3; i += 1) {
      particlesPositions[i] = (Math.random() - 0.5) * 50;
    }
    particlesGeometry.setAttribute("position", new THREE.BufferAttribute(particlesPositions, 3));
    const particles = new THREE.Points(
      particlesGeometry,
      new THREE.PointsMaterial({ size: 0.1, color: 0x3498db, transparent: true, opacity: 0.8 })
    );
    scene.add(particles);
    camera.position.z = 15;

    const fontLoader = new FontLoader();
    fontLoader.load(
      "https://threejs.org/examples/fonts/helvetiker_regular.typeface.json",
      (font) => {
        const textGeometry = new TextGeometry("AI Recruiter", { font, size: 2, height: 0.3 });
        const textMesh = new THREE.Mesh(
          textGeometry,
          new THREE.MeshStandardMaterial({ color: 0x3498db, emissive: 0x1e90ff, emissiveIntensity: 0.6 })
        );
        textGeometry.computeBoundingBox();
        const box = textGeometry.boundingBox;
        textMesh.position.set(-(box.max.x - box.min.x) / 2, -(box.max.y - box.min.y) / 2, -10);
        scene.add(textMesh);
        const startTime = performance.now();
        const animateText = (time) => {
          const progress = Math.min((time - startTime) / 2000, 1);
          const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
          textMesh.position.z = -10 + eased * 10;
          textMesh.scale.setScalar(0.5 + eased * 0.5);
          if (progress < 1) requestAnimationFrame(animateText);
          else finish();
        };
        requestAnimationFrame(animateText);
      },
      undefined,
      finish
    );

    let animationId;
    const animate = () => {
      const positions = particlesGeometry.attributes.position.array;
      for (let i = 0; i < particlesCount * 3; i += 3) {
        positions[i + 1] += 0.02 * Math.sin(i + Date.now() * 0.001);
        positions[i] += 0.01 * Math.sin(i + Date.now() * 0.001);
        if (positions[i + 1] > 25) positions[i + 1] = -25;
      }
      particlesGeometry.attributes.position.needsUpdate = true;
      renderer.render(scene, camera);
      animationId = requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.clearTimeout(giveUp);
      cancelAnimationFrame(animationId);
      window.removeEventListener("resize", onResize);
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

  return <div ref={mountRef} className="intro-mount" />;
}
