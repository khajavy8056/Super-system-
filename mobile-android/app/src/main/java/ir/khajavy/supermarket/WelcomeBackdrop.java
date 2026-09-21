package ir.khajavy.supermarket;

/** Lightweight vector waves: no bitmap allocation, animation, network or layout work. */
public final class WelcomeBackdrop extends android.graphics.drawable.Drawable {
    private final android.graphics.Paint paint = new android.graphics.Paint(3);
    private final android.graphics.Path path = new android.graphics.Path();
    @Override public void draw(android.graphics.Canvas canvas) {
        android.graphics.Rect b = getBounds();
        float w = b.width(), h = b.height();
        canvas.save(); canvas.translate(b.left, b.top); canvas.drawColor(Ui.BG);
        paint.setShader(new android.graphics.LinearGradient(0, h*.76f, w, h,
            new int[]{0xFF155AE8, 0xFF955CFF, 0xFF142A77}, null, android.graphics.Shader.TileMode.CLAMP));
        path.reset(); path.moveTo(0, h*.86f);
        path.cubicTo(w*.38f, h*.68f, w*.57f, h*1.01f, w, h*.78f);
        path.lineTo(w,h); path.lineTo(0,h); path.close(); canvas.drawPath(path,paint);
        paint.setShader(new android.graphics.LinearGradient(0,h,w,h*.8f,0xFF082456,0xFF3744C9,android.graphics.Shader.TileMode.CLAMP));
        path.reset(); path.moveTo(0,h*.97f); path.cubicTo(w*.3f,h*.75f,w*.7f,h*1.04f,w,h*.9f);
        path.lineTo(w,h); path.lineTo(0,h); path.close(); canvas.drawPath(path,paint);
        paint.setShader(null); canvas.restore();
    }
    @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); }
    @Override public void setColorFilter(android.graphics.ColorFilter filter) { paint.setColorFilter(filter); }
    @Override public int getOpacity() { return android.graphics.PixelFormat.OPAQUE; }
}
