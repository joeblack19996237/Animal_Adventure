import Phaser from 'phaser';
import './styles.css';
import { BootScene } from './scenes/BootScene';
import { LoginScene } from './scenes/LoginScene';
import { PreloadScene } from './scenes/PreloadScene';
import { GameScene } from './scenes/GameScene';
import { UIScene } from './scenes/UIScene';

const gameConfig: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  width: window.innerWidth,
  height: window.innerHeight,
  backgroundColor: '#000000',
  scene: [BootScene, LoginScene, PreloadScene, GameScene, UIScene],
  parent: 'game-container',
  pixelArt: true,
  roundPixels: true,
  antialias: false,
};

new Phaser.Game(gameConfig);
