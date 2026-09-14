package ir.khajavy.supermarket;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;

/** v3.0 — minimal read-only provider so a backup file can be shared with other apps (no androidx dependency). */
public final class BackupProvider extends ContentProvider {
    public static Uri uri(android.content.Context c, File f) { return Uri.parse("content://" + c.getPackageName() + ".backup/" + Uri.encode(f.getName())); }
    private File file(Uri u) { File dir = new File(getContext().getExternalFilesDir(null), "backups"); File f = new File(dir, u.getLastPathSegment()); if (!f.getParentFile().equals(dir)) throw new SecurityException(); return f; }
    @Override public boolean onCreate() { return true; }
    @Override public ParcelFileDescriptor openFile(Uri u, String mode) throws java.io.FileNotFoundException { return ParcelFileDescriptor.open(file(u), ParcelFileDescriptor.MODE_READ_ONLY); }
    @Override public Cursor query(Uri u, String[] proj, String sel, String[] args, String sort) { File f = file(u); String[] cols = proj == null ? new String[]{"_display_name", "_size"} : proj; MatrixCursor c = new MatrixCursor(cols); Object[] row = new Object[cols.length]; for (int i = 0; i < cols.length; i++) row[i] = "_display_name".equals(cols[i]) ? f.getName() : "_size".equals(cols[i]) ? f.length() : null; c.addRow(row); return c; }
    @Override public String getType(Uri u) { return "application/octet-stream"; }
    @Override public Uri insert(Uri u, ContentValues v) { return null; }
    @Override public int delete(Uri u, String s, String[] a) { return 0; }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { return 0; }
}
