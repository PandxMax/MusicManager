package com.pandxmax.musicmanager

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun MMTheme(content: @Composable () -> Unit) {
    val accent = Color(Store.dynamicAccent ?: Store.accent)
    val scheme = if (Store.dark) {
        darkColorScheme(
            primary = accent, onPrimary = Color.White, secondary = accent,
            background = Color(0xFF14141C), onBackground = Color(0xFFEDEDF5),
            surface = Color(0xFF1C1C26), onSurface = Color(0xFFEDEDF5),
            surfaceVariant = Color(0xFF262633), onSurfaceVariant = Color(0xFFB8B8C8),
            outline = Color(0xFF3A3A4D)
        )
    } else {
        lightColorScheme(
            primary = accent, onPrimary = Color.White, secondary = accent,
            background = Color(0xFFF6F6FA), onBackground = Color(0xFF1B1B25),
            surface = Color.White, onSurface = Color(0xFF1B1B25),
            surfaceVariant = Color(0xFFE9E9F2), onSurfaceVariant = Color(0xFF55556A),
            outline = Color(0xFFCFCFDD)
        )
    }
    MaterialTheme(colorScheme = scheme, content = content)
}

@Composable
fun IconBtn(text: String, enabled: Boolean = true, accent: Boolean = false, onClick: () -> Unit) {
    val bg = if (accent && enabled) MaterialTheme.colorScheme.primary else Color.Transparent
    val fg = if (accent && enabled) Color.White
    else if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.3f)
    Box(
        Modifier.size(42.dp).clip(CircleShape).background(bg).clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center
    ) { Text(text, fontSize = 20.sp, color = fg) }
}

@Composable
fun Bar(title: String, onBack: (() -> Unit)?, actions: @Composable RowScope.() -> Unit = {}) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 2.dp) {
        Row(
            Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (onBack != null) IconBtn("←", onClick = onBack)
            Text(
                title, Modifier.weight(1f).padding(horizontal = 8.dp), maxLines = 1,
                overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.SemiBold
            )
            actions()
        }
    }
}

@Composable
fun Chip(text: String, modifier: Modifier = Modifier) {
    Surface(
        modifier, shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.surfaceVariant,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline)
    ) {
        Text(text, Modifier.padding(PaddingValues(horizontal = 9.dp, vertical = 3.dp)), fontSize = 11.sp, maxLines = 1)
    }
}

@Composable
fun CoverThumb(path: String, px: Int, modifier: Modifier) {
    val bmp by produceState<Bitmap?>(null, path, Store.coverVersion) {
        value = withContext(Dispatchers.IO) { Covers.thumb(path, px) }
    }
    val b = bmp
    if (b != null) {
        Image(b.asImageBitmap(), null, modifier, contentScale = ContentScale.Crop)
    } else {
        Box(modifier.background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
            Text("♪", fontSize = 28.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
