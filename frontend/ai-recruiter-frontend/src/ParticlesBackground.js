import { useEffect, useRef } from "react";
import * as THREE from "three";
import { prefersReducedMotion } from "./api";

export default function ParticlesBackground() {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    const reduced = prefersReducedMotion();
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    mount.appendChild(renderer.domElement);

    const particlesGeometry = new THREE.BufferGeometry();
    const particlesCount = 900;
    const particlesPositions = new Float32Array(particlesCount * 3);
    for (let i = 0; i < particlesCount * 3; i += 1) {
      particlesPositions[i] = (Math.random() - 0.5) * 50;
    }
    particlesGeometry.setAttribute("position", new THREE.BufferAttribute(particlesPositions, 3));
    const particles = new THREE.Points(
      particlesGeometry,
      new THREE.PointsMaterial({ size: 0.08, color: 0x3498db, transparent: true, opacity: 0.55 })
    );
    scene.add(particles);
    camera.position.z = 15;

    let animationId;
    const renderFrame = () => {
      if (!reduced) {
        const positions = particlesGeometry.attributes.position.array;
        for (let i = 0; i < particlesCount * 3; i += 3) {
          positions[i + 1] += 0.015 * Math.sin(i + Date.now() * 0.001);
          positions[i] += 0.008 * Math.sin(i + Date.now() * 0.001);
          if (positions[i + 1] > 25) positions[i + 1] = -25;
        }
        particlesGeometry.attributes.position.needsUpdate = true;
      }
      renderer.render(scene, camera);
      if (!reduced) animationId = requestAnimationFrame(renderFrame);
    };
    renderFrame();

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
      if (reduced) renderer.render(scene, camera);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener("resize", onResize);
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

  return <div ref={mountRef} className="particles" aria-hidden="true" />;
}
