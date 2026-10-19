-- Lop du lieu chuan hoa nghiep vu. Airflow chi ghi vao cac bang tb_ nay.

CREATE TABLE IF NOT EXISTS dm_thanh_pho (
    thanh_pho_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ma_thanh_pho VARCHAR(10) NOT NULL UNIQUE,
    ten_thanh_pho VARCHAR(100) NOT NULL UNIQUE,
    vung VARCHAR(100) NOT NULL,
    vi_do NUMERIC(8, 5) NOT NULL,
    kinh_do NUMERIC(8, 5) NOT NULL,
    vung_khi_hau VARCHAR(50) NOT NULL,
    hoat_dong BOOLEAN NOT NULL DEFAULT TRUE,
    tao_luc TIMESTAMPTZ NOT NULL DEFAULT now(),
    cap_nhat_luc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dm_ngay (
    ngay_id DATE PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS dm_nguon_du_lieu (
    nguon_du_lieu_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ma_nguon VARCHAR(30) NOT NULL UNIQUE,
    ten_nguon VARCHAR(100) NOT NULL,
    dia_chi_api VARCHAR(255),
    loai_nguon VARCHAR(30) NOT NULL,
    tao_luc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dm_dieu_kien_thoi_tiet (
    dieu_kien_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ma_thoi_tiet SMALLINT NOT NULL UNIQUE,
    ten_dieu_kien VARCHAR(100) NOT NULL,
    mo_ta VARCHAR(255) NOT NULL,
    nhom_muc_do VARCHAR(30) NOT NULL,
    tao_luc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dm_chi_so_thoi_tiet (
    chi_so_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ma_chi_so VARCHAR(50) NOT NULL UNIQUE,
    ten_chi_so VARCHAR(100) NOT NULL,
    nhom_chi_so VARCHAR(50) NOT NULL,
    ma_don_vi VARCHAR(20) NOT NULL,
    ten_don_vi VARCHAR(50) NOT NULL,
    kieu_du_lieu VARCHAR(20) NOT NULL CHECK (kieu_du_lieu IN ('SO', 'DUNG_SAI', 'CHU')),
    cach_tong_hop VARCHAR(20) NOT NULL CHECK (
        cach_tong_hop IN ('TRUNG_BINH', 'TONG', 'NHO_NHAT', 'LON_NHAT', 'CUOI_CUNG', 'BAT_KY')
    ),
    mo_ta VARCHAR(255),
    hoat_dong BOOLEAN NOT NULL DEFAULT TRUE,
    tao_luc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tb_lan_nap_du_lieu (
    lan_nap_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bat_dau_luc TIMESTAMPTZ NOT NULL DEFAULT now(),
    ket_thuc_luc TIMESTAMPTZ,
    trang_thai VARCHAR(20) NOT NULL CHECK (trang_thai IN ('DANG_CHAY', 'THANH_CONG', 'THAT_BAI')),
    so_thanh_pho INTEGER NOT NULL DEFAULT 0,
    so_quan_sat INTEGER NOT NULL DEFAULT 0,
    so_gia_tri INTEGER NOT NULL DEFAULT 0,
    loi TEXT
);

CREATE TABLE IF NOT EXISTS tb_quan_sat_thoi_tiet (
    quan_sat_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thanh_pho_id BIGINT NOT NULL REFERENCES dm_thanh_pho(thanh_pho_id),
    nguon_du_lieu_id BIGINT NOT NULL REFERENCES dm_nguon_du_lieu(nguon_du_lieu_id),
    dieu_kien_id BIGINT REFERENCES dm_dieu_kien_thoi_tiet(dieu_kien_id),
    loai_quan_sat VARCHAR(30) NOT NULL CHECK (
        loai_quan_sat IN ('HIEN_TAI', 'DU_BAO_GIO', 'DU_BAO_NGAY')
    ),
    thoi_diem_quan_sat TIMESTAMP NOT NULL,
    ngay_id DATE NOT NULL REFERENCES dm_ngay(ngay_id),
    lay_luc TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (thanh_pho_id, loai_quan_sat, thoi_diem_quan_sat)
);

CREATE TABLE IF NOT EXISTS tb_gia_tri_quan_sat (
    quan_sat_id BIGINT NOT NULL REFERENCES tb_quan_sat_thoi_tiet(quan_sat_id) ON DELETE CASCADE,
    chi_so_id BIGINT NOT NULL REFERENCES dm_chi_so_thoi_tiet(chi_so_id),
    gia_tri_so NUMERIC(12, 4),
    gia_tri_dung_sai BOOLEAN,
    gia_tri_chu TEXT,
    PRIMARY KEY (quan_sat_id, chi_so_id),
    CHECK (num_nonnulls(gia_tri_so, gia_tri_dung_sai, gia_tri_chu) = 1)
);

CREATE INDEX IF NOT EXISTS idx_tb_quan_sat_thanh_pho_thoi_diem
    ON tb_quan_sat_thoi_tiet (thanh_pho_id, thoi_diem_quan_sat DESC);
CREATE INDEX IF NOT EXISTS idx_tb_quan_sat_ngay_loai
    ON tb_quan_sat_thoi_tiet (ngay_id, loai_quan_sat);
CREATE INDEX IF NOT EXISTS idx_tb_gia_tri_chi_so
    ON tb_gia_tri_quan_sat (chi_so_id, quan_sat_id);

INSERT INTO dm_thanh_pho (ma_thanh_pho, ten_thanh_pho, vung, vi_do, kinh_do, vung_khi_hau)
VALUES
    ('HN', 'Ha Noi', 'Dong bang song Hong', 21.02850, 105.85420, 'Mien Bac'),
    ('HP', 'Hai Phong', 'Dong bang song Hong', 20.84490, 106.68810, 'Mien Bac'),
    ('HL', 'Ha Long', 'Dong Bac Bo', 20.95000, 107.07300, 'Mien Bac'),
    ('TB', 'Thai Binh', 'Dong bang song Hong', 20.44630, 106.33660, 'Mien Bac'),
    ('V', 'Vinh', 'Bac Trung Bo', 18.67960, 105.68130, 'Mien Trung'),
    ('HUE', 'Hue', 'Bac Trung Bo', 16.46370, 107.59090, 'Mien Trung'),
    ('DN', 'Da Nang', 'Nam Trung Bo', 16.05440, 108.20220, 'Mien Trung'),
    ('NT', 'Nha Trang', 'Nam Trung Bo', 12.23880, 109.19670, 'Mien Trung'),
    ('BMT', 'Buon Ma Thuot', 'Tay Nguyen', 12.66670, 108.05000, 'Tay Nguyen'),
    ('HCM', 'Ho Chi Minh', 'Dong Nam Bo', 10.82310, 106.62970, 'Mien Nam'),
    ('CT', 'Can Tho', 'Dong bang song Cuu Long', 10.04520, 105.74690, 'Mien Nam'),
    ('PQ', 'Phu Quoc', 'Dong bang song Cuu Long', 10.28990, 103.98400, 'Mien Nam')
ON CONFLICT (ma_thanh_pho) DO UPDATE SET
    ten_thanh_pho = EXCLUDED.ten_thanh_pho,
    vung = EXCLUDED.vung,
    vi_do = EXCLUDED.vi_do,
    kinh_do = EXCLUDED.kinh_do,
    vung_khi_hau = EXCLUDED.vung_khi_hau,
    cap_nhat_luc = now();

INSERT INTO dm_nguon_du_lieu (ma_nguon, ten_nguon, dia_chi_api, loai_nguon)
VALUES ('OPEN_METEO', 'Open-Meteo Forecast API', 'https://api.open-meteo.com/v1/forecast', 'API')
ON CONFLICT (ma_nguon) DO UPDATE SET
    ten_nguon = EXCLUDED.ten_nguon,
    dia_chi_api = EXCLUDED.dia_chi_api,
    loai_nguon = EXCLUDED.loai_nguon;

INSERT INTO dm_dieu_kien_thoi_tiet (ma_thoi_tiet, ten_dieu_kien, mo_ta, nhom_muc_do)
VALUES
    (0, 'Troi quang', 'Troi quang hoac it may', 'Binh thuong'),
    (1, 'It may', 'Troi chu yeu quang', 'Binh thuong'),
    (2, 'May rai rac', 'May rai rac', 'Binh thuong'),
    (3, 'Nhieu may', 'Troi nhieu may', 'Binh thuong'),
    (45, 'Suong mu', 'Suong mu', 'Han che tam nhin'),
    (48, 'Suong muoi', 'Suong muoi', 'Han che tam nhin'),
    (51, 'Mua phun nhe', 'Mua phun nhe', 'Mua'),
    (53, 'Mua phun vua', 'Mua phun vua', 'Mua'),
    (55, 'Mua phun to', 'Mua phun to', 'Mua'),
    (61, 'Mua nhe', 'Mua nhe', 'Mua'),
    (63, 'Mua vua', 'Mua vua', 'Mua'),
    (65, 'Mua to', 'Mua to', 'Mua lon'),
    (71, 'Tuyet nhe', 'Tuyet nhe', 'Tuyet'),
    (73, 'Tuyet vua', 'Tuyet vua', 'Tuyet'),
    (75, 'Tuyet to', 'Tuyet to', 'Tuyet'),
    (80, 'Mua rao nhe', 'Mua rao nhe', 'Mua'),
    (81, 'Mua rao vua', 'Mua rao vua', 'Mua'),
    (82, 'Mua rao manh', 'Mua rao manh', 'Mua lon'),
    (95, 'Dong', 'Dong', 'Dong'),
    (96, 'Dong kem mua da nhe', 'Dong kem mua da nhe', 'Nguy hiem'),
    (99, 'Dong kem mua da manh', 'Dong kem mua da manh', 'Nguy hiem')
ON CONFLICT (ma_thoi_tiet) DO UPDATE SET
    ten_dieu_kien = EXCLUDED.ten_dieu_kien,
    mo_ta = EXCLUDED.mo_ta,
    nhom_muc_do = EXCLUDED.nhom_muc_do;

INSERT INTO dm_chi_so_thoi_tiet (
    ma_chi_so, ten_chi_so, nhom_chi_so, ma_don_vi, ten_don_vi,
    kieu_du_lieu, cach_tong_hop, mo_ta
)
VALUES
    ('nhiet_do_c', 'Nhiet do', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'TRUNG_BINH', 'Nhiet do khong khi'),
    ('cam_nhan_c', 'Nhiet do cam nhan', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'TRUNG_BINH', 'Nhiet do cam nhan'),
    ('do_am_pct', 'Do am tuong doi', 'Do am', 'PERCENT', 'Phan tram', 'SO', 'TRUNG_BINH', 'Do am tuong doi'),
    ('luong_mua_mm', 'Luong mua', 'Mua', 'MM', 'Milimet', 'SO', 'TONG', 'Tong luong mua'),
    ('mua_mm', 'Mua', 'Mua', 'MM', 'Milimet', 'SO', 'TONG', 'Luong mua dang rain'),
    ('xac_suat_mua_pct', 'Xac suat mua', 'Mua', 'PERCENT', 'Phan tram', 'SO', 'TRUNG_BINH', 'Xac suat co mua'),
    ('ap_suat_hpa', 'Ap suat', 'Khi tuong', 'HPA', 'Hectopascal', 'SO', 'TRUNG_BINH', 'Ap suat muc nuoc bien'),
    ('may_phu_pct', 'Do che phu may', 'May', 'PERCENT', 'Phan tram', 'SO', 'TRUNG_BINH', 'Do che phu may'),
    ('toc_do_gio_kmh', 'Toc do gio', 'Gio', 'KMH', 'Kilomet/gio', 'SO', 'TRUNG_BINH', 'Toc do gio'),
    ('gio_giat_kmh', 'Gio giat', 'Gio', 'KMH', 'Kilomet/gio', 'SO', 'LON_NHAT', 'Toc do gio giat'),
    ('tam_nhin_m', 'Tam nhin', 'Tam nhin', 'METER', 'Met', 'SO', 'TRUNG_BINH', 'Tam nhin ngang'),
    ('nhiet_do_thap_nhat_c', 'Nhiet do thap nhat', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'NHO_NHAT', 'Nhiet do thap nhat trong ngay'),
    ('nhiet_do_cao_nhat_c', 'Nhiet do cao nhat', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'LON_NHAT', 'Nhiet do cao nhat trong ngay'),
    ('cam_nhan_thap_nhat_c', 'Cam nhan thap nhat', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'NHO_NHAT', 'Nhiet do cam nhan thap nhat'),
    ('cam_nhan_cao_nhat_c', 'Cam nhan cao nhat', 'Nhiet do', 'DEG_C', 'Do C', 'SO', 'LON_NHAT', 'Nhiet do cam nhan cao nhat'),
    ('tong_luong_mua_mm', 'Tong luong mua ngay', 'Mua', 'MM', 'Milimet', 'SO', 'TONG', 'Tong luong mua trong ngay'),
    ('tong_mua_mm', 'Tong mua ngay', 'Mua', 'MM', 'Milimet', 'SO', 'TONG', 'Tong rain trong ngay'),
    ('tong_mua_rao_mm', 'Tong mua rao ngay', 'Mua', 'MM', 'Milimet', 'SO', 'TONG', 'Tong mua rao trong ngay'),
    ('tuyet_roi_cm', 'Tuyet roi', 'Tuyet', 'CM', 'Centimet', 'SO', 'TONG', 'Luong tuyet roi'),
    ('so_gio_co_mua', 'So gio co mua', 'Mua', 'HOUR', 'Gio', 'SO', 'TONG', 'So gio co mua'),
    ('toc_do_gio_toi_da_kmh', 'Toc do gio toi da', 'Gio', 'KMH', 'Kilomet/gio', 'SO', 'LON_NHAT', 'Toc do gio toi da trong ngay'),
    ('gio_giat_toi_da_kmh', 'Gio giat toi da', 'Gio', 'KMH', 'Kilomet/gio', 'SO', 'LON_NHAT', 'Gio giat toi da trong ngay'),
    ('thoi_luong_nang_gio', 'Thoi luong nang', 'Buc xa', 'HOUR', 'Gio', 'SO', 'TONG', 'Thoi luong nang'),
    ('thoi_luong_ban_ngay_gio', 'Thoi luong ban ngay', 'Buc xa', 'HOUR', 'Gio', 'SO', 'TONG', 'Thoi luong ban ngay'),
    ('la_ban_ngay', 'Ban ngay', 'Thoi gian', 'BOOLEAN', 'Dung/Sai', 'DUNG_SAI', 'BAT_KY', 'Co phai ban ngay khong')
ON CONFLICT (ma_chi_so) DO UPDATE SET
    ten_chi_so = EXCLUDED.ten_chi_so,
    nhom_chi_so = EXCLUDED.nhom_chi_so,
    ma_don_vi = EXCLUDED.ma_don_vi,
    ten_don_vi = EXCLUDED.ten_don_vi,
    kieu_du_lieu = EXCLUDED.kieu_du_lieu,
    cach_tong_hop = EXCLUDED.cach_tong_hop,
    mo_ta = EXCLUDED.mo_ta;

INSERT INTO dm_ngay (
    ngay_id, nam, quy, thang, ten_thang, tuan_trong_nam,
    ngay_trong_thang, thu_trong_tuan, ten_thu, la_cuoi_tuan
)
SELECT
    d::date,
    EXTRACT(YEAR FROM d)::smallint,
    EXTRACT(QUARTER FROM d)::smallint,
    EXTRACT(MONTH FROM d)::smallint,
    'Thang ' || EXTRACT(MONTH FROM d)::int,
    EXTRACT(WEEK FROM d)::smallint,
    EXTRACT(DAY FROM d)::smallint,
    EXTRACT(ISODOW FROM d)::smallint,
    CASE EXTRACT(ISODOW FROM d)::int
        WHEN 1 THEN 'Thu 2' WHEN 2 THEN 'Thu 3' WHEN 3 THEN 'Thu 4'
        WHEN 4 THEN 'Thu 5' WHEN 5 THEN 'Thu 6' WHEN 6 THEN 'Thu 7'
        ELSE 'Chu nhat'
    END,
    EXTRACT(ISODOW FROM d)::int IN (6, 7)
FROM generate_series('2020-01-01'::date, '2030-12-31'::date, interval '1 day') AS dates(d)
ON CONFLICT (ngay_id) DO NOTHING;
