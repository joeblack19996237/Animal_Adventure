import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

describe('visual asset integration', () => {
  it('loads Fredoka globally for DOM and Phaser-facing UI', () => {
    const css = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf-8');
    const main = readFileSync(join(process.cwd(), 'src/main.ts'), 'utf-8');
    expect(main).toContain("import './styles.css';");
    expect(css).toContain('Fredoka-Regular.ttf');
    expect(css).toContain('Fredoka-SemiBold.ttf');
    expect(css).toContain('Fredoka-Bold.ttf');
    expect(css).toContain("font-family: 'Fredoka', system-ui, sans-serif");
  });

  it('uses the main menu background and image-only character grid assets', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/LoginView.ts'), 'utf-8');
    expect(source).toContain('/assets/images/UI/ui_main_menu_bg.png');
    expect(source).toContain('/assets/images/logo.png');
    expect(source).toContain('/assets/images/UI/lock.png');
    expect(source).toContain('/assets/images/cat_snowman_sprite_sheet/cat-front-stand.png');
    expect(source).toContain('/assets/images/arctic_fox_sprite_sheet/arctic_fox_stand_front.png');
    expect(source).toContain('/assets/images/penguin_sprite_sheet/penguin_stand_front.png');
    expect(source).not.toContain('Choose your character');
  });

  it('uses image-based HUD, menu, panels, quest dialog, and timer bars', () => {
    const source = readFileSync(join(process.cwd(), 'src/scenes/game/GameDomController.ts'), 'utf-8');
    expect(source).toContain('ui_currency_icon.png');
    expect(source).toContain('ui_level_badge.png');
    expect(source).toContain('V2_Resources/UI_frame.png');
    expect(source).toContain('ui_friend_list_panel.png');
    expect(source).toContain('ui_shop_panel.png');
    expect(source).toContain('ui_inventory_panel.png');
    expect(source).toContain('ui_minimap_frame.png');
    expect(source).toContain('ui_dialog_box.png');
    expect(source).toContain('ui_cancel_button.png');
    expect(source).toContain('ui_confirm_button.png');
    expect(source).toContain('ui_task_timer_bar_green.png');
    expect(source).toContain('ui_task_timer_bar_red.png');
  });
});
