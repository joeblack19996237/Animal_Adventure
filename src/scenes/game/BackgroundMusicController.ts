import Phaser from 'phaser';
import assetsJson from '../../../config/assets.json';

type AssetManifest = Record<string, string>;

const ASSETS = assetsJson as AssetManifest;
const BGM_TRACKS = Object.entries(ASSETS)
  .filter(([key]) => key.startsWith('bgm_'))
  .sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }))
  .map(([key, url]) => ({ key, url }));

export function loadBackgroundMusic(scene: Phaser.Scene): void {
  for (const track of BGM_TRACKS) {
    if (!scene.cache.audio.exists(track.key)) {
      scene.load.audio(track.key, track.url);
    }
  }
}

export class BackgroundMusicController {
  private current: Phaser.Sound.BaseSound | null = null;
  private started = false;

  constructor(
    private readonly scene: Phaser.Scene,
    private readonly volume = 0.35,
  ) {}

  startAfterUserGesture(): void {
    if (this.started || BGM_TRACKS.length === 0) return;
    this.started = true;
    this.playCurrentTrack();
  }

  destroy(): void {
    this.current?.stop();
    this.current?.destroy();
    this.current = null;
  }

  private playCurrentTrack(): void {
    const track = BGM_TRACKS[0];
    const sound = this.scene.sound.add(track.key, { volume: this.volume, loop: true });
    this.current = sound;
    sound.play();
  }
}
