-- Lop star schema phuc vu dashboard.
-- Cac bang dim_ va fact_ duoc sinh tu dm_ va tb_ nghiep vu.

DROP TABLE IF EXISTS fact_tong_hop_thoi_tiet, fact_chi_tiet_thoi_tiet,
    dim_chi_so_thoi_tiet, dim_dieu_kien_thoi_tiet, dim_nguon_du_lieu,
    dim_ngay, dim_thanh_pho CASCADE;

CREATE TABLE IF NOT EXISTS dim_thanh_pho (
    thanh_pho_key BIGINT PRIMARY KEY,
    nguon_thanh_pho_id BIGINT NOT NULL UNIQUE REFERENCES dm_thanh_pho(thanh_pho_id),
    ma_thanh_pho VARCHAR(10) NOT NULL UNIQUE,
    ten_thanh_pho VARCHAR(100) NOT NULL,
    vung VARCHAR(100) NOT NULL,
    vi_do NUMERIC(8, 5) NOT NULL,
    kinh_do NUMERIC(8, 5) NOT NULL,
    vung_khi_hau VARCHAR(50) NOT NULL,
    hoat_dong BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_ngay (
    ngay_key DATE PRIMARY KEY,
    nam SMALLINT NOT NULL,
    quy SMALLINT NOT NULL,
    thang SMALLINT NOT NULL,
    ten_thang VARCHAR(20) NOT NULL,
    tuan_trong_nam SMALLINT NOT NULL,
    ngay_trong_thang SMALLINT NOT NULL,
    thu_trong_tuan SMALLINT NOT NULL,
    ten_thu VARCHAR(20) NOT NULL,
    la_cuoi_tuan BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_nguon_du_lieu (
    nguon_du_lieu_key BIGINT PRIMARY KEY,
    nguon_du_lieu_id BIGINT NOT NULL UNIQUE REFERENCES dm_nguon_du_lieu(nguon_du_lieu_id),
    ma_nguon VARCHAR(30) NOT NULL UNIQUE,
    ten_nguon VARCHAR(100) NOT NULL,
    dia_chi_api VARCHAR(255),
    loai_nguon VARCHAR(30) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_dieu_kien_thoi_tiet (
    dieu_kien_key BIGINT PRIMARY KEY,
    dieu_kien_id BIGINT NOT NULL UNIQUE REFERENCES dm_dieu_kien_thoi_tiet(dieu_kien_id),
    ma_thoi_tiet SMALLINT NOT NULL UNIQUE,
    ten_dieu_kien VARCHAR(100) NOT NULL,
    mo_ta VARCHAR(255) NOT NULL,
    nhom_muc_do VARCHAR(30) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_chi_so_thoi_tiet (
    chi_so_key BIGINT PRIMARY KEY,
    chi_so_id BIGINT NOT NULL UNIQUE REFERENCES dm_chi_so_thoi_tiet(chi_so_id),
    ma_chi_so VARCHAR(50) NOT NULL UNIQUE,
    ten_chi_so VARCHAR(100) NOT NULL,
    nhom_chi_so VARCHAR(50) NOT NULL,
    ma_don_vi VARCHAR(20) NOT NULL,
    ten_don_vi VARCHAR(50) NOT NULL,
    kieu_du_lieu VARCHAR(20) NOT NULL,
    cach_tong_hop VARCHAR(20) NOT NULL,
    mo_ta VARCHAR(255),
    hoat_dong BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_chi_tiet_thoi_tiet (
    quan_sat_id BIGINT NOT NULL,
    thanh_pho_key BIGINT NOT NULL REFERENCES dim_thanh_pho(thanh_pho_key),
    ngay_key DATE NOT NULL REFERENCES dim_ngay(ngay_key),
    dieu_kien_key BIGINT REFERENCES dim_dieu_kien_thoi_tiet(dieu_kien_key),
    chi_so_key BIGINT NOT NULL REFERENCES dim_chi_so_thoi_tiet(chi_so_key),
    nguon_du_lieu_key BIGINT NOT NULL REFERENCES dim_nguon_du_lieu(nguon_du_lieu_key),
    loai_quan_sat VARCHAR(30) NOT NULL,
    thoi_diem_quan_sat TIMESTAMP NOT NULL,
    gia_tri_so NUMERIC(12, 4),
    gia_tri_dung_sai BOOLEAN,
    gia_tri_chu TEXT,
    lay_luc TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (quan_sat_id, chi_so_key)
);

CREATE TABLE IF NOT EXISTS fact_tong_hop_thoi_tiet (
    quan_sat_id BIGINT PRIMARY KEY,
    thanh_pho_key BIGINT NOT NULL REFERENCES dim_thanh_pho(thanh_pho_key),
    ngay_key DATE NOT NULL REFERENCES dim_ngay(ngay_key),
    dieu_kien_key BIGINT REFERENCES dim_dieu_kien_thoi_tiet(dieu_kien_key),
    nguon_du_lieu_key BIGINT NOT NULL REFERENCES dim_nguon_du_lieu(nguon_du_lieu_key),
    loai_quan_sat VARCHAR(30) NOT NULL,
    thoi_diem_quan_sat TIMESTAMP NOT NULL,
    nhiet_do_c NUMERIC(12, 4),
    cam_nhan_c NUMERIC(12, 4),
    do_am_pct NUMERIC(12, 4),
    luong_mua_mm NUMERIC(12, 4),
    mua_mm NUMERIC(12, 4),
    xac_suat_mua_pct NUMERIC(12, 4),
    ap_suat_hpa NUMERIC(12, 4),
    may_phu_pct NUMERIC(12, 4),
    toc_do_gio_kmh NUMERIC(12, 4),
    gio_giat_kmh NUMERIC(12, 4),
    tam_nhin_m NUMERIC(12, 4),
    nhiet_do_thap_nhat_c NUMERIC(12, 4),
    nhiet_do_cao_nhat_c NUMERIC(12, 4),
    cam_nhan_thap_nhat_c NUMERIC(12, 4),
    cam_nhan_cao_nhat_c NUMERIC(12, 4),
    tong_luong_mua_mm NUMERIC(12, 4),
    tong_mua_mm NUMERIC(12, 4),
    tong_mua_rao_mm NUMERIC(12, 4),
    tuyet_roi_cm NUMERIC(12, 4),
    so_gio_co_mua NUMERIC(12, 4),
    toc_do_gio_toi_da_kmh NUMERIC(12, 4),
    gio_giat_toi_da_kmh NUMERIC(12, 4),
    thoi_luong_nang_gio NUMERIC(12, 4),
    thoi_luong_ban_ngay_gio NUMERIC(12, 4),
    la_ban_ngay BOOLEAN,
    lay_luc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_tong_hop_thanh_pho_ngay
    ON fact_tong_hop_thoi_tiet (thanh_pho_key, ngay_key);
CREATE INDEX IF NOT EXISTS idx_fact_tong_hop_loai_thoi_diem
    ON fact_tong_hop_thoi_tiet (loai_quan_sat, thoi_diem_quan_sat);
CREATE INDEX IF NOT EXISTS idx_fact_chi_tiet_chi_so_ngay
    ON fact_chi_tiet_thoi_tiet (chi_so_key, ngay_key);

CREATE OR REPLACE FUNCTION lam_moi_du_lieu_dashboard()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE fact_chi_tiet_thoi_tiet, fact_tong_hop_thoi_tiet;
    TRUNCATE dim_chi_so_thoi_tiet, dim_dieu_kien_thoi_tiet,
        dim_nguon_du_lieu, dim_ngay, dim_thanh_pho CASCADE;

    INSERT INTO dim_thanh_pho (
        thanh_pho_key, nguon_thanh_pho_id, ma_thanh_pho, ten_thanh_pho,
        vung, vi_do, kinh_do, vung_khi_hau, hoat_dong
    )
    SELECT thanh_pho_id, thanh_pho_id, ma_thanh_pho, ten_thanh_pho,
           vung, vi_do, kinh_do, vung_khi_hau, hoat_dong
    FROM dm_thanh_pho;

    INSERT INTO dim_ngay (
        ngay_key, nam, quy, thang, ten_thang, tuan_trong_nam,
        ngay_trong_thang, thu_trong_tuan, ten_thu, la_cuoi_tuan
    )
    SELECT ngay_id, nam, quy, thang, ten_thang, tuan_trong_nam,
           ngay_trong_thang, thu_trong_tuan, ten_thu, la_cuoi_tuan
    FROM dm_ngay;

    INSERT INTO dim_nguon_du_lieu (
        nguon_du_lieu_key, nguon_du_lieu_id, ma_nguon, ten_nguon, dia_chi_api, loai_nguon
    )
    SELECT nguon_du_lieu_id, nguon_du_lieu_id, ma_nguon, ten_nguon, dia_chi_api, loai_nguon
    FROM dm_nguon_du_lieu;

    INSERT INTO dim_dieu_kien_thoi_tiet (
        dieu_kien_key, dieu_kien_id, ma_thoi_tiet, ten_dieu_kien, mo_ta, nhom_muc_do
    )
    SELECT dieu_kien_id, dieu_kien_id, ma_thoi_tiet, ten_dieu_kien, mo_ta, nhom_muc_do
    FROM dm_dieu_kien_thoi_tiet;

    INSERT INTO dim_chi_so_thoi_tiet (
        chi_so_key, chi_so_id, ma_chi_so, ten_chi_so, nhom_chi_so,
        ma_don_vi, ten_don_vi, kieu_du_lieu, cach_tong_hop, mo_ta, hoat_dong
    )
    SELECT chi_so_id, chi_so_id, ma_chi_so, ten_chi_so, nhom_chi_so,
           ma_don_vi, ten_don_vi, kieu_du_lieu, cach_tong_hop, mo_ta, hoat_dong
    FROM dm_chi_so_thoi_tiet;

    INSERT INTO fact_chi_tiet_thoi_tiet (
        quan_sat_id, thanh_pho_key, ngay_key, dieu_kien_key, chi_so_key,
        nguon_du_lieu_key, loai_quan_sat, thoi_diem_quan_sat,
        gia_tri_so, gia_tri_dung_sai, gia_tri_chu, lay_luc
    )
    SELECT q.quan_sat_id, q.thanh_pho_id, q.ngay_id, q.dieu_kien_id,
           g.chi_so_id, q.nguon_du_lieu_id, q.loai_quan_sat,
           q.thoi_diem_quan_sat, g.gia_tri_so, g.gia_tri_dung_sai,
           g.gia_tri_chu, q.lay_luc
    FROM tb_quan_sat_thoi_tiet q
    JOIN tb_gia_tri_quan_sat g ON g.quan_sat_id = q.quan_sat_id;

    INSERT INTO fact_tong_hop_thoi_tiet (
        quan_sat_id, thanh_pho_key, ngay_key, dieu_kien_key, nguon_du_lieu_key,
        loai_quan_sat, thoi_diem_quan_sat,
        nhiet_do_c, cam_nhan_c, do_am_pct, luong_mua_mm, mua_mm,
        xac_suat_mua_pct, ap_suat_hpa, may_phu_pct, toc_do_gio_kmh,
        gio_giat_kmh, tam_nhin_m, nhiet_do_thap_nhat_c, nhiet_do_cao_nhat_c,
        cam_nhan_thap_nhat_c, cam_nhan_cao_nhat_c, tong_luong_mua_mm,
        tong_mua_mm, tong_mua_rao_mm, tuyet_roi_cm, so_gio_co_mua,
        toc_do_gio_toi_da_kmh, gio_giat_toi_da_kmh, thoi_luong_nang_gio,
        thoi_luong_ban_ngay_gio, la_ban_ngay, lay_luc
    )
    SELECT
        q.quan_sat_id, q.thanh_pho_id, q.ngay_id, q.dieu_kien_id,
        q.nguon_du_lieu_id, q.loai_quan_sat, q.thoi_diem_quan_sat,
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'nhiet_do_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'cam_nhan_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'do_am_pct'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'luong_mua_mm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'mua_mm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'xac_suat_mua_pct'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'ap_suat_hpa'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'may_phu_pct'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'toc_do_gio_kmh'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'gio_giat_kmh'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'tam_nhin_m'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'nhiet_do_thap_nhat_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'nhiet_do_cao_nhat_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'cam_nhan_thap_nhat_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'cam_nhan_cao_nhat_c'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'tong_luong_mua_mm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'tong_mua_mm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'tong_mua_rao_mm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'tuyet_roi_cm'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'so_gio_co_mua'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'toc_do_gio_toi_da_kmh'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'gio_giat_toi_da_kmh'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'thoi_luong_nang_gio'),
        MAX(g.gia_tri_so) FILTER (WHERE c.ma_chi_so = 'thoi_luong_ban_ngay_gio'),
        BOOL_OR(g.gia_tri_dung_sai) FILTER (WHERE c.ma_chi_so = 'la_ban_ngay'),
        q.lay_luc
    FROM tb_quan_sat_thoi_tiet q
    JOIN tb_gia_tri_quan_sat g ON g.quan_sat_id = q.quan_sat_id
    JOIN dm_chi_so_thoi_tiet c ON c.chi_so_id = g.chi_so_id
    GROUP BY q.quan_sat_id, q.thanh_pho_id, q.ngay_id, q.dieu_kien_id,
             q.nguon_du_lieu_id, q.loai_quan_sat, q.thoi_diem_quan_sat, q.lay_luc;
END;
$$;

SELECT lam_moi_du_lieu_dashboard();
